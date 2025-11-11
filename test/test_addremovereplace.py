from PySide6.QtCore import QCoreApplication, QMimeData, Qt, QUrl
from PySide6.QtGui import QDropEvent

from .fixtures.fixture_gui import GUI
from .mocks.mock_rvcr2 import converts, currentModelName
from .mocks.mock_voicecards import deleteVoiceCard


def dropFiles(gui: GUI, voiceCardIndex: int, *files: str) -> bool:
    voiceCards = gui.window.windowAreaWidget.voiceCards

    # Only the placeholder is present.
    assert voiceCards.count() > voiceCardIndex
    dropForImportPlaceholderWidget = voiceCards.itemWidget(voiceCards.item(0))

    # Build a QMimeData with file URLs
    mime = QMimeData()
    urls = [QUrl.fromLocalFile(path) for path in files]
    mime.setUrls(urls)

    # Create a drop event at the center of the widget.
    pos = dropForImportPlaceholderWidget.rect().center()
    dropEvent = QDropEvent(
        pos,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    # Send the event to the container widget.
    voiceCards.dropEvent(dropEvent)

    return dropEvent.isAccepted()


def testAdd(qtbot, gui):
    voiceCards = gui.window.windowAreaWidget.voiceCards

    # Only the placeholder is present.
    assert voiceCards.count() == 1

    # Drop new files to import onto the placeholder.
    assert dropFiles(gui, 0, "model.pth", "model-index.index")

    # Wait for queued signals that change the selection.
    QCoreApplication.processEvents()

    # Check that it's selected.
    assert voiceCards.currentRow() == 0

    # Check that it's imported and loaded but not running.
    assert voiceCards.count() == 2
    assert gui.vcm.vcLoaded
    assert gui.audioHolder.audio is None


def testRemoveRunningOne(qtbot, savedTwoVoiceCards, gui):
    voiceCards = gui.window.windowAreaWidget.voiceCards

    # Two cards and a placeholder.
    assert voiceCards.count() == 3

    # Run the first one.
    qtbot.mouseClick(
        voiceCards.itemWidget(voiceCards.item(0)), Qt.MouseButton.LeftButton
    )
    qtbot.mouseClick(gui.window.windowAreaWidget.startButton, Qt.MouseButton.LeftButton)

    # Check that it is selected.
    assert voiceCards.currentRow() == 0

    # Check that it is running.
    assert gui.vcm.vcLoaded
    assert gui.audioHolder.audio is not None
    assert converts(gui.audioHolder)
    assert currentModelName(gui.vcm) == "m0"

    # Delete the running one.
    deleteVoiceCard(voiceCards, 0)

    # Check that the new running one is selected and has the index 0.
    assert voiceCards.count() == 2
    assert voiceCards.currentRow() == 0
    assert voiceCards.itemWidget(voiceCards.currentItem()).toolTip() == "m1"

    # Check that it is running.
    assert gui.vcm.vcLoaded
    assert gui.audioHolder.audio is not None
    assert converts(gui.audioHolder)
    assert currentModelName(gui.vcm) == "m1"


def testRemoveNonRunningOne(qtbot, savedTwoVoiceCards, gui):
    voiceCards = gui.window.windowAreaWidget.voiceCards

    # Two cards and a placeholder.
    assert voiceCards.count() == 3

    # Run the second one.
    qtbot.mouseClick(
        voiceCards.itemWidget(voiceCards.item(1)), Qt.MouseButton.LeftButton
    )
    qtbot.mouseClick(gui.window.windowAreaWidget.startButton, Qt.MouseButton.LeftButton)

    # Check that it is selected.
    assert voiceCards.currentRow() == 1

    # Check that it is running.
    assert gui.vcm.vcLoaded
    assert gui.audioHolder.audio is not None
    assert converts(gui.audioHolder)
    assert currentModelName(gui.vcm) == "m1"

    # Delete the non-running one.
    deleteVoiceCard(voiceCards, 0)

    # Check that the running one is still selected and has the index 0.
    assert voiceCards.count() == 2
    assert voiceCards.currentRow() == 0
    assert voiceCards.itemWidget(voiceCards.currentItem()).toolTip() == "m1"

    # Check that it is still running.
    assert gui.vcm.vcLoaded
    assert gui.audioHolder.audio is not None
    assert converts(gui.audioHolder)
    assert currentModelName(gui.vcm) == "m1"


def testNoRemovePlaceholder(qtbot, savedTwoVoiceCards, gui):
    voiceCards = gui.window.windowAreaWidget.voiceCards

    # Two cards and a placeholder.
    assert voiceCards.count() == 3

    # Try to delete the placeholder.
    deleteVoiceCard(voiceCards, 2)

    # Still two cards and a placeholder.
    assert voiceCards.count() == 3


def testReplaceRunning(qtbot, savedVoiceCard, gui):
    voiceCards = gui.window.windowAreaWidget.voiceCards

    # One card and a placeholder.
    assert voiceCards.count() == 2

    # Run.
    qtbot.mouseClick(
        voiceCards.itemWidget(voiceCards.item(1)), Qt.MouseButton.LeftButton
    )
    qtbot.mouseClick(gui.window.windowAreaWidget.startButton, Qt.MouseButton.LeftButton)

    # Check that it is selected.
    assert voiceCards.currentRow() == 0

    # Check that it is running.
    assert gui.vcm.vcLoaded
    assert gui.audioHolder.audio is not None
    assert converts(gui.audioHolder)
    assert currentModelName(gui.vcm) == "m0"

    # Drop new files to import onto the existing one.
    assert dropFiles(gui, 0, "model.pth", "model-index.index")

    # Wait for queued signals that change the selection.
    QCoreApplication.processEvents()

    # Check that it's selected.
    assert voiceCards.currentRow() == 0

    # Check that it's imported, loaded and running.
    assert voiceCards.count() == 2
    assert gui.vcm.vcLoaded
    assert gui.audioHolder.audio is not None
    assert converts(gui.audioHolder)
    assert currentModelName(gui.vcm) == "model"
