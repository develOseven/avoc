import pytest
from PySide6.QtCore import QSettings, Qt

from .mocks.mock_rvcr2 import converts, silences
from .mocks.mock_voicecards import deleteCurrentVoiceCard


def testStart(qtbot, savedVoiceCard, gui):
    # Check that it is loaded, but not running.
    assert gui.vcm.vcLoaded
    assert gui.audioHolder.audio is None

    qtbot.mouseClick(gui.window.windowAreaWidget.startButton, Qt.MouseButton.LeftButton)

    # Check that it has started running.
    assert gui.vcm.vcLoaded
    assert gui.audioHolder.audio is not None


@pytest.fixture
def wasRunningBefore():
    # Settings as it was running at app exit.
    interfaceSettings = QSettings()
    interfaceSettings.beginGroup("InterfaceSettings")
    interfaceSettings.setValue("running", True)


def testStartAtLaunch(qtbot, savedVoiceCard, wasRunningBefore, gui):
    # Check that it has started running immediately after launch.
    assert gui.vcm.vcLoaded
    assert gui.audioHolder.audio is not None
    assert converts(gui.audioHolder)


def testNoStartIfNoModels(qtbot, gui):
    # Check that it is not running.
    assert not gui.vcm.vcLoaded
    assert gui.audioHolder.audio is None

    qtbot.mouseClick(gui.window.windowAreaWidget.startButton, Qt.MouseButton.LeftButton)

    # Check that it has not started running.
    assert not gui.vcm.vcLoaded
    assert gui.audioHolder.audio is None


def testStopOnDelete(qtbot, savedVoiceCard, gui):
    qtbot.mouseClick(gui.window.windowAreaWidget.startButton, Qt.MouseButton.LeftButton)

    # Check that it has started running.
    assert gui.vcm.vcLoaded
    assert gui.audioHolder.audio is not None
    assert converts(gui.audioHolder)

    # Delete the current voice card that is running.
    deleteCurrentVoiceCard(gui.window.windowAreaWidget.voiceCards)

    # Check that it has stopped but kept the audio open.
    assert not gui.vcm.vcLoaded
    assert gui.audioHolder.audio is not None
    assert silences(gui.audioHolder)
