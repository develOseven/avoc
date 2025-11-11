from collections import namedtuple
from dataclasses import dataclass

import pytest

from avoc.main import (
    AudioHolder,
    MainWindow,
    VoiceChangerManager,
    create,
    deinitialize,
    initialize,
)
from avoc.voicecardsmanager import VoiceCardsManager


@dataclass
class GUI:
    window: MainWindow
    voiceCardsManager: VoiceCardsManager
    vcm: VoiceChangerManager
    audioHolder: AudioHolder


@pytest.fixture
def gui(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    voiceCardsManager, vcm, audioHolder = create()
    initialize(window, voiceCardsManager, vcm, audioHolder)
    yield GUI(window, voiceCardsManager, vcm, audioHolder)
    deinitialize(audioHolder)
