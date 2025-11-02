import ctypes
import queue
import random
import string
import threading
from typing import Callable

import numpy as np
import pipewire_filtertools as pfts
from voiceconversion.utils.VoiceChangerModel import AudioInOutFloat

DELAY_WINDOW_SIZE_BLOCKS = 16


class LoopCtx(ctypes.Structure):
    """For the case when quantum is smaller."""

    _fields_ = [
        ("buffer_ptr", ctypes.POINTER(ctypes.c_float)),
        ("n_samples", ctypes.c_size_t),
    ]


def run(
    loop: ctypes.c_void_p,
    name: str,
    sampleRate: int,
    blockSamplesCount: int,
    changeVoice: Callable[
        [AudioInOutFloat], tuple[AudioInOutFloat, float, list[int], tuple | None]
    ],
):
    ArrayType = ctypes.c_float * blockSamplesCount
    ctx = LoopCtx(ArrayType(), 0)
    ctx_p = ctypes.pointer(ctx)

    fsize = ctypes.sizeof(ctypes.c_float)
    memmove_addr = ctypes.cast(ctypes.memmove, ctypes.c_void_p).value
    assert memmove_addr is not None
    npmemmove = ctypes.CFUNCTYPE(
        ctypes.c_void_p,
        ctypes.c_void_p,
        np.ctypeslib.ndpointer(dtype=np.float32, ndim=1, flags="C_CONTIGUOUS"),
        ctypes.c_size_t,
    )(memmove_addr)

    # Background worker setup for non-matching block size
    workQ: queue.Queue[np.ndarray] = queue.Queue(maxsize=1)
    resultQ: queue.Queue[np.ndarray] = queue.Queue(maxsize=1)
    stopEvent = threading.Event()

    def nonMatchingBlockSizeWorker():
        """Thread that runs changeVoice asynchronously."""
        while not stopEvent.is_set():
            try:
                inBuff = workQ.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                outBuff, _, _, _ = changeVoice(inBuff)
                outBuff = np.ascontiguousarray(outBuff.astype(np.float32))
                with resultQ.mutex:
                    resultQ.queue.clear()
                resultQ.put(outBuff)
            except Exception as e:
                print(f"[AudioPipeWire worker] Error: {e}")

    nonMatchingBlockSizeWorkerThread = threading.Thread(
        target=nonMatchingBlockSizeWorker
    )
    nonMatchingBlockSizeWorkerThread.start()

    prevOutBuffer = np.zeros(blockSamplesCount, dtype=np.float32)
    currOutBuffer = np.zeros(blockSamplesCount, dtype=np.float32)
    samplesOutputOffs = 0  # offset from the start of the oldest buffer

    sampleDelayAccum = 0
    samplesDelayWindow = [blockSamplesCount] * DELAY_WINDOW_SIZE_BLOCKS

    def onProcessNonMatching(c_ctx, in_samples, out_samples, n_samples):
        nonlocal prevOutBuffer
        nonlocal currOutBuffer
        nonlocal samplesOutputOffs
        nonlocal sampleDelayAccum
        nonlocal samplesDelayWindow

        lc = ctypes.cast(c_ctx, ctypes.POINTER(LoopCtx)).contents

        sampleDelayAccum += n_samples

        try:
            buffer = resultQ.get_nowait()
            prevOutBuffer = currOutBuffer
            currOutBuffer = buffer
            samplesDelayWindow = samplesDelayWindow[1:] + [sampleDelayAccum]
            sampleDelayAccum = 0
            if samplesOutputOffs >= 2 * blockSamplesCount:
                # If two buffers aren't enough, drop. Different block size needed.
                samplesOutputOffs = max(
                    0, 2 * blockSamplesCount - max(samplesDelayWindow)
                )
            elif samplesOutputOffs >= blockSamplesCount:
                # The curr is now prev.
                samplesOutputOffs -= blockSamplesCount
        except queue.Empty:
            pass

        if samplesOutputOffs < blockSamplesCount:
            start = samplesOutputOffs
            npmemmove(
                out_samples,
                prevOutBuffer[start : start + n_samples],
                n_samples * fsize,
            )
        elif samplesOutputOffs < 2 * blockSamplesCount:
            start = samplesOutputOffs - blockSamplesCount
            npmemmove(
                out_samples,
                currOutBuffer[start : start + n_samples],
                n_samples * fsize,
            )
        else:
            # If two buffers aren't enough, drop. Different block size needed.
            ctypes.memmove(
                out_samples, (ctypes.c_char * (n_samples * fsize))(), n_samples * fsize
            )

        samplesOutputOffs += n_samples

        toCopyCount = min(blockSamplesCount - lc.n_samples, n_samples)
        dst_ptr = ctypes.cast(
            ctypes.addressof(lc.buffer_ptr.contents) + lc.n_samples * fsize,
            ctypes.POINTER(ctypes.c_float),
        )
        ctypes.memmove(dst_ptr, in_samples, toCopyCount * fsize)
        lc.n_samples += toCopyCount

        if lc.n_samples == blockSamplesCount:
            # Full block ready
            lc.n_samples = 0
            audioInBuff = np.ctypeslib.as_array(
                lc.buffer_ptr, shape=(blockSamplesCount,)
            ).astype(np.float32)
            try:
                workQ.put_nowait(audioInBuff.copy())
            except queue.Full:
                # Drop if queue is busy to avoid blocking realtime
                pass

    @pfts.PIPEWIRE_FILTERTOOLS_ON_PROCESS
    def on_process(c_ctx, in_samples, out_samples, n_samples):
        assert n_samples <= blockSamplesCount

        if n_samples < blockSamplesCount:
            # Smaller blocks mode: accumulate and process in background thread
            # Happens when we start after a smaller quantum was chosen.
            onProcessNonMatching(c_ctx, in_samples, out_samples, n_samples)
        else:
            # Full-sized blocks mode: process immediately (synchronous fast path)
            audioInBuff = np.ctypeslib.as_array(
                in_samples, shape=(blockSamplesCount,)
            ).astype(np.float32)
            out_wav, _, _, _ = changeVoice(audioInBuff)
            npmemmove(out_samples, out_wav, blockSamplesCount * fsize)

    try:
        pfts.main_loop_run(
            ctypes.cast(ctx_p, ctypes.c_void_p),
            loop,
            name.encode("utf-8"),
            sampleRate,
            blockSamplesCount,
            on_process,
        )
    finally:
        stopEvent.set()
        nonMatchingBlockSizeWorkerThread.join()
        pfts.deinit()


class AudioPipeWire:
    def __init__(
        self,
        sampleRate: int,
        blockSamplesCount: int,
        changeVoice,
    ):
        super().__init__()

        randId = "".join(random.choices(string.ascii_letters + string.digits, k=4))

        pfts.init()
        self.loop = pfts.main_loop_new()

        self.thread = threading.Thread(
            target=run,
            args=(
                self.loop,
                f"AVoc_{randId}",
                sampleRate,
                blockSamplesCount,
                changeVoice,
            ),
        )
        self.thread.start()

    def exit(self):
        if self.loop is not None:
            pfts.main_loop_quit(self.loop)
            self.thread.join()
            self.loop = None
