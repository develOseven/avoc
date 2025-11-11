from unittest.mock import patch

import pytest

from avoc.audiobackends import HAS_PIPEWIRE

if HAS_PIPEWIRE:
    from ..mocks.mock_audiopipewire import MockAudioPipeWire
else:
    from ..mocks.mock_audioqtmultimedia import MockAudioQtMultimedia

from ..mocks.mock_rvcr2 import MockRVCr2


@pytest.fixture(autouse=True)
def patchRVCr2():
    with patch("avoc.main.RVCr2", MockRVCr2):
        yield


@pytest.fixture(autouse=True)
def patchAudio():
    if HAS_PIPEWIRE:
        with patch("avoc.main.AudioPipeWire", MockAudioPipeWire):
            yield
    else:
        with patch("avoc.main.AudioQtMultimedia", MockAudioQtMultimedia):
            yield
