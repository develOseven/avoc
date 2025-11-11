from typing import Tuple
from unittest.mock import MagicMock

import numpy as np
import torch
from voiceconversion.common.deviceManager.DeviceManager import DeviceManager
from voiceconversion.utils.VoiceChangerModel import AudioInOutFloat
from voiceconversion.voice_changer_settings import VoiceChangerSettings

from avoc.main import AudioHolder, VoiceChangerManager


class MockRVCr2:
    """Mock version of RVCr2 for testing without GPU or audio dependencies."""

    def __init__(self, settings: VoiceChangerSettings):
        self.settings = settings
        self.device = DeviceManager.get_instance().device
        self.voiceChangerType = "RVC"
        self.pipeline = MagicMock()
        self.convert_buffer = None
        self.pitch_buffer = None
        self.pitchf_buffer = None
        self.resampler_in = MagicMock()
        self.resampler_out = MagicMock()

    def initialize(self, force_reload: bool, pretrain_dir: str):
        pass

    def change_pitch_extractor(self, pretrain_dir: str):
        pass

    def realloc(
        self,
        block_frame: int,
        extra_frame: int,
        crossfade_frame: int,
        sola_search_frame: int,
    ):
        pass

    def convert(self, audio_in: AudioInOutFloat, sample_rate: int) -> torch.Tensor:
        return torch.as_tensor(audio_in, dtype=torch.float32)

    def inference(self, audio_in: AudioInOutFloat) -> Tuple[torch.Tensor | None, float]:
        # Not a precise output length, just use an x4 approximation.
        return (
            torch.full(
                (len(audio_in) * 4,), 0.2, dtype=torch.float32, device=self.device
            ),
            0.42,
        )


def converts(audioHolder: AudioHolder) -> bool:
    blockSamplesCount = audioHolder.audio.blockSamplesCount
    assert blockSamplesCount != 0
    buff = np.full(blockSamplesCount, 0.1, dtype=np.float32)
    outBuff, _, _, _ = audioHolder.audio.changeVoice(buff)
    assert len(outBuff) == blockSamplesCount
    return np.isclose(outBuff[-1], 0.2, atol=0.05)


def silences(audioHolder: AudioHolder) -> bool:
    blockSamplesCount = audioHolder.audio.blockSamplesCount
    assert blockSamplesCount != 0
    buff = np.full(blockSamplesCount, 0.1, dtype=np.float32)
    outBuff, _, _, _ = audioHolder.audio.changeVoice(buff)
    assert len(outBuff) == blockSamplesCount
    return np.array_equal(outBuff, np.zeros(blockSamplesCount, dtype=np.float32))


def currentModelName(vcm: VoiceChangerManager) -> str:
    return vcm.vcs[-1].settings.rvcImportedModelInfo.name
