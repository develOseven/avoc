import copy
import ctypes
import threading
from typing import Callable

import numpy as np
import pipewire_filtertools as pfts
from voiceconversion.utils.VoiceChangerModel import AudioInOutFloat


class LoopCtx(ctypes.Structure):
    _fields_ = [
        ("buffer_ptr", ctypes.POINTER(ctypes.c_float)),
        ("buffer_size", ctypes.c_size_t),
        ("n_samples", ctypes.c_uint32),
        ("have_data", ctypes.c_int),
    ]


def run(
    loop: ctypes.c_void_p,
    sampleRate: int,
    blockSamplesCount: int,
    changeVoice: Callable[
        [AudioInOutFloat], tuple[AudioInOutFloat, float, list[int], tuple | None]
    ],
):
    buf_size = blockSamplesCount * 2
    ArrayType = ctypes.c_float * buf_size
    buffer = ArrayType()
    ctx = LoopCtx(buffer, buf_size, 0, 0)
    ctx_p = ctypes.pointer(ctx)

    ON_BUFFER = pfts.PIPEWIRE_FILTERTOOLS_ON_BUFFER
    memmove_addr = ctypes.cast(ctypes.memmove, ctypes.c_void_p).value
    assert memmove_addr is not None
    npmemmove = ctypes.CFUNCTYPE(
        ctypes.c_void_p,
        ctypes.c_void_p,
        np.ctypeslib.ndpointer(dtype=np.float32, ndim=1, flags="C_CONTIGUOUS"),
        ctypes.c_size_t,
    )(memmove_addr)
    fsize = ctypes.sizeof(ctypes.c_float)

    @ON_BUFFER
    def on_capture(c_ctx, samples, n_samples):
        lc = ctypes.cast(c_ctx, ctypes.POINTER(LoopCtx)).contents
        assert n_samples == blockSamplesCount
        audioInBuff = np.ctypeslib.as_array(samples, shape=(n_samples,))
        out_wav, _, _, _ = changeVoice(audioInBuff.astype(np.float32))

        npmemmove(lc.buffer_ptr, out_wav, n_samples * fsize)

        lc.n_samples = n_samples
        lc.have_data = 1

    @ON_BUFFER
    def on_playback(c_ctx, samples, n_samples):
        lc = ctypes.cast(c_ctx, ctypes.POINTER(LoopCtx)).contents
        if lc.have_data:
            n = min(n_samples, lc.n_samples)
            ctypes.memmove(samples, lc.buffer_ptr, n * fsize)
            lc.have_data = 0
        else:
            ctypes.memmove(
                samples, (ctypes.c_char * (n_samples * fsize))(), n_samples * fsize
            )

    pfts.main_loop_run(
        ctypes.cast(ctx_p, ctypes.c_void_p),
        loop,
        sampleRate,
        blockSamplesCount,
        on_capture,
        on_playback,
    )
    pfts.deinit()


class AudioPipeWire:
    def __init__(
        self,
        sampleRate: int,
        blockSamplesCount: int,
        changeVoice,
    ):
        super().__init__()

        pfts.init()

        self.loop = pfts.main_loop_new()

        self.thread = threading.Thread(
            target=run,
            args=(
                self.loop,
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
