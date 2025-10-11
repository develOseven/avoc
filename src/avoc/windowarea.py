import json
import os
import re
import shutil
from typing import Iterable, List

from PySide6.QtCore import QModelIndex, QSettings, QSize, Qt, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFontMetrics,
    QImageReader,
    QPalette,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from voiceconversion.utils.LoadModelParams import LoadModelParamFile, LoadModelParams

from .audiosettings import AudioSettingsGroupBox
from .exceptions import FailedToMoveVoiceCardException

VOICE_CARD_SIZE = QSize(188, 262)
VOICE_CARD_MARGIN = 8

UNKNOWN_MODEL_NAME = "Unknown Model"
DROP_MODEL_FILES = "Drop model files here<br><b>*.pth</b> and <b>*.index</b><br><br>"
DROP_ICON_FILE = "Drop icon file here<br><b>*.png</b>, <b>*.jpeg</b>, <b>*.gif</b>..."
START_TXT = "Start"
RUNNING_TXT = "Running..."


def voiceCardForSlot(modelDir: str, row: int) -> QWidget:
    folder = str(row)
    paramsFilePath = os.path.join(modelDir, folder, "params.json")
    if os.path.exists(paramsFilePath):
        name = UNKNOWN_MODEL_NAME
        with open(paramsFilePath) as f:
            params = json.load(f)
            iconFileName = params.get("iconFile", "")
            name = params.get("name", name)
            if iconFileName:
                pixmap = QPixmap(os.path.join(modelDir, folder, iconFileName))
                label = QLabel()
                label.setPixmap(cropCenterScalePixmap(pixmap, VOICE_CARD_SIZE))
                return label
    return VoiceCardPlaceholderWidget(
        VOICE_CARD_SIZE, f"{name}<br><br>{DROP_ICON_FILE}"
    )


class WindowAreaWidget(QWidget):
    def __init__(self, modelDir: str, parent: QWidget | None = None):
        super().__init__(parent)

        self.modelDir = modelDir

        layout = QVBoxLayout()

        self.voiceCards = VoiceCardsContainer(modelDir)

        layout.addWidget(self.voiceCards, stretch=2)

        controlsLayout = QHBoxLayout()

        self.audioSettingsGroupBox = AudioSettingsGroupBox()
        controlsLayout.addWidget(self.audioSettingsGroupBox, stretch=3)

        modelSettingsGroupBox = QGroupBox("Settings for the Active Voice Model")
        modelSettingsGroupBox.setEnabled(False)  # TODO: implement
        modelSettingsLayout = QGridLayout()
        row = 0
        pitchSlider = QSlider(Qt.Orientation.Horizontal)
        modelSettingsLayout.addWidget(QLabel("Pitch"), row, 0)
        modelSettingsLayout.addWidget(pitchSlider, row, 1)
        row += 1
        formantShiftSlider = QSlider(Qt.Orientation.Horizontal)
        modelSettingsLayout.addWidget(QLabel("Formant Shift"), row, 0)
        modelSettingsLayout.addWidget(formantShiftSlider, row, 1)
        row += 1
        indexSlider = QSlider(Qt.Orientation.Horizontal)
        modelSettingsLayout.addWidget(QLabel("Index"), row, 0)
        modelSettingsLayout.addWidget(indexSlider, row, 1)
        modelSettingsGroupBox.setLayout(modelSettingsLayout)
        controlsLayout.addWidget(modelSettingsGroupBox, stretch=1)

        self.startButton = QPushButton(START_TXT)
        # Make the Start button size fixed.
        fm = QFontMetrics(self.startButton.font())
        maxStartButtonWidth = int(
            max(fm.horizontalAdvance(t) for t in [START_TXT, RUNNING_TXT]) * 1.618
        )
        self.startButton.setMinimumWidth(maxStartButtonWidth)
        # Make the Start button toggle and change text when clicked.
        self.startButton.setCheckable(True)
        self.startButton.toggled.connect(
            lambda checked: self.startButton.setText(
                RUNNING_TXT if checked else START_TXT
            )
        )
        # Unfortunately can't drag the cards while the voice conversion is running
        # because it will select them and load.
        self.startButton.toggled.connect(
            lambda checked: self.voiceCards.setDragDropMode(
                QAbstractItemView.DragDropMode.DropOnly
                if checked
                else QAbstractItemView.DragDropMode.InternalMove
            )
        )
        # Can't change audio settings while running.
        self.startButton.toggled.connect(
            lambda checked: self.audioSettingsGroupBox.setEnabled(not checked)
        )
        controlsLayout.addWidget(self.startButton)

        layout.addLayout(controlsLayout, stretch=1)

        self.setLayout(layout)

        modelDirToModelIcon: dict[str, QWidget] = {}

        os.makedirs(modelDir, exist_ok=True)

        for folder in os.listdir(modelDir):
            if folder.isdigit() and os.path.isdir(os.path.join(modelDir, folder)):
                modelDirToModelIcon[folder] = voiceCardForSlot(modelDir, int(folder))

        for folder in sortedNumerically(modelDirToModelIcon):
            self.voiceCards.addWidget(modelDirToModelIcon[folder])

        self.voiceCards.addWidget(
            VoiceCardPlaceholderWidget(
                VOICE_CARD_SIZE, DROP_MODEL_FILES + DROP_ICON_FILE
            ),
            selectable=False,
        )

        self.voiceCards.model().rowsMoved.connect(self.rearrangeVoiceModelDirs)

        settings = QSettings()
        settings.beginGroup("Interface")

        self.voiceCards.setCurrentRow(int(settings.value("currentVoiceCardIndex", 0)))
        self.voiceCards.currentRowChanged.connect(
            lambda row: settings.setValue("currentVoiceCardIndex", row)
        )

        # Disable the start button if there are no voice cards.
        self.voiceCards.currentRowChanged.connect(
            lambda row: self.startButton.setEnabled(row >= 0)
        )
        self.startButton.setEnabled(self.voiceCards.currentRow() >= 0)

    def rearrangeVoiceModelDirs(
        self,
        sourceParent: QModelIndex,
        sourceStart: int,
        sourceEnd: int,
        destinationParent: QModelIndex,
        destinationRow: int,
    ):
        if sourceStart != sourceEnd:
            raise FailedToMoveVoiceCardException

        dirs = sorted(
            [d for d in os.listdir(self.modelDir) if d.isdigit()], key=lambda x: int(x)
        )
        total = len(dirs)

        if not (0 <= sourceStart < total) or not (0 <= destinationRow <= total):
            raise FailedToMoveVoiceCardException("Invalid indices")

        if destinationRow > sourceStart:
            destinationRow -= 1

        # Create a temp name for the moving directory to avoid name conflicts
        src_path = os.path.join(self.modelDir, str(sourceStart))
        tmp_path = os.path.join(self.modelDir, "_tmp_move")
        shutil.move(src_path, tmp_path)

        # Renumber other directories depending on move direction
        if sourceStart < destinationRow:
            # Shift everything between (sourceStart+1 ... destinationRow) up by one
            for i in range(sourceStart + 1, destinationRow + 1):
                os.rename(
                    os.path.join(self.modelDir, str(i)),
                    os.path.join(self.modelDir, str(i - 1)),
                )
        else:
            # Shift everything between (destinationRow ... sourceStart-1) down by one
            for i in range(sourceStart - 1, destinationRow - 1, -1):
                os.rename(
                    os.path.join(self.modelDir, str(i)),
                    os.path.join(self.modelDir, str(i + 1)),
                )

        # Move the temp folder into its new numbered slot
        shutil.move(tmp_path, os.path.join(self.modelDir, str(destinationRow)))


class FlowContainer(QListWidget):
    def __init__(self):
        super().__init__()

        # Allow dragging the cards around
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

        # make it look like a normal scroll area
        self.viewport().setBackgroundRole(QPalette.Window)
        # display items from left to right, instead of top to bottom
        self.setFlow(QListView.Flow.LeftToRight)
        # wrap items that don't fit the width of the viewport
        # similar to self.setViewMode(self.IconMode)
        self.setWrapping(True)
        # always re-layout items when the view is resized
        self.setResizeMode(QListView.ResizeMode.Adjust)

        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        # Add margins for the items to make the selection frame around a card visible.
        self.setStyleSheet(
            f"""
            QListWidget::item {{
                margin:{VOICE_CARD_MARGIN}px;
            }}
            """
        )

    def addWidget(self, widget: QWidget, selectable: bool = True):
        item = QListWidgetItem()
        if not selectable:
            item.setFlags(
                item.flags()
                & ~(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            )
        self.addItem(item)
        item.setSizeHint(widget.sizeHint())
        self.setItemWidget(item, widget)

    def insertWidget(self, row: int, widget: QWidget):
        item = QListWidgetItem()
        self.insertItem(row, item)
        item.setSizeHint(widget.sizeHint())
        self.setItemWidget(item, widget)


class FlowContainerWithFixedLast(FlowContainer):
    def canDropBeforLast(self, event: QDropEvent):
        """Forbid going past the last item which is the voice card placeholder."""
        row = self.indexAt(event.pos()).row()
        if row == self.count() - 1:
            itemRect = self.visualRect(self.model().index(self.count() - 1, 0))
            return event.pos().x() < itemRect.center().x()
        return row > 0

    def dragMoveEvent(self, event: QDragMoveEvent):
        if self.canDropBeforLast(event):
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent):
        # InternalMove drops to rearrange cards.
        if self.canDropBeforLast(event):
            super().dropEvent(event)
        else:
            # Hack to clear a failed drop indicator
            self.setDropIndicatorShown(False)
            self.viewport().update()
            self.setDropIndicatorShown(True)


class VoiceCardsContainer(FlowContainerWithFixedLast):

    droppedModelFiles = Signal(LoadModelParams)
    droppedIconFile = Signal(int, str)

    def __init__(self, modelDir: str):
        super().__init__()
        self.modelDir = modelDir

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent):
        if not event.mimeData().hasUrls():
            # InternalMove drops to rearrange cards.
            return super().dropEvent(event)

        # External drop to import models and icons.

        files = [url for url in event.mimeData().urls() if url.isLocalFile()]
        pthFiles = [file for file in files if file.toString().endswith(".pth")]
        indexFiles = [file for file in files if file.toString().endswith(".index")]
        iconFiles = [
            file
            for file in files
            if not file.toString().endswith(".pth")
            and not file.toString().endswith(".index")
        ]
        if len(pthFiles) != len(indexFiles):
            QMessageBox.critical(
                self,
                "Error Importing a Voice Model",
                "Both files expected: *.pth and *.index",
            )
            return
        if len(indexFiles) == 1:
            indexFile = indexFiles[0].toLocalFile()
            if os.path.basename(indexFile).startswith("trained"):
                QMessageBox.critical(
                    self,
                    "Error Importing a Voice Model",
                    f"Use the 'added' index, not the 'trained'.\n\nFile:\n{indexFile}",
                )
                return
        if len(iconFiles) > 1:
            QMessageBox.critical(
                self,
                "Error Importing an Icon",
                "Only one icon file expected.",
            )
        if len(iconFiles) == 1:
            iconFile = iconFiles[0].toLocalFile()
            supportedImageFormats = QImageReader.supportedImageFormats()
            iconFileExt = os.path.splitext(iconFile)[1][1:].lower()
            if iconFileExt.encode("utf-8") not in supportedImageFormats:
                QMessageBox.critical(
                    self,
                    "Error Importing an Icon",
                    f"Failed to import an icon for a voice card.\n\nFile:\n{iconFile}",
                )
                return

        row = self.indexAt(event.pos()).row()
        importingNew = row < 0 or row >= self.count()
        slot = self.count() - 1 if importingNew else row

        if len(indexFiles) == 1:
            self.droppedModelFiles.emit(
                LoadModelParams(
                    voiceChangerType="RVC",
                    slot=slot,
                    isSampleMode=False,
                    sampleId="",
                    files=[
                        LoadModelParamFile(
                            name=pthFiles[0].toLocalFile(), kind="rvcModel", dir=""
                        ),
                        LoadModelParamFile(
                            name=indexFiles[0].toLocalFile(), kind="rvcIndex", dir=""
                        ),
                    ],
                    params={},
                )
            )

        if len(iconFiles) == 1 and slot < self.count() - 1:
            self.droppedIconFile.emit(slot, iconFiles[0].toLocalFile())

    def onVoiceCardUpdated(self, row: int):
        if row >= self.count() - 1:
            self.insertWidget(row, voiceCardForSlot(self.modelDir, row))
        else:
            self.setItemWidget(self.item(row), voiceCardForSlot(self.modelDir, row))


class VoiceCardPlaceholderWidget(QWidget):
    def __init__(self, cardSize: QSize, text: str, parent: QWidget | None = None):
        super().__init__(parent)

        self.cardSize = cardSize
        self.setStyleSheet("border: 2px solid;")

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        dropHere = QLabel(text)
        dropHere.setTextFormat(Qt.TextFormat.RichText)
        dropHere.setWordWrap(True)
        dropHere.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(dropHere)
        self.setLayout(layout)

    def sizeHint(self):
        return self.cardSize


def cropCenterScalePixmap(pixmap: QPixmap, targetSize: QSize) -> QPixmap:
    # Original size
    ow = pixmap.width()
    oh = pixmap.height()

    # Maintain target ratio
    target_ratio = targetSize.width() / targetSize.height()
    orig_ratio = ow / oh

    if orig_ratio > target_ratio:
        # Original is too wide → crop horizontally
        cropW = int(oh * target_ratio)
        cropH = oh
        x = (ow - cropW) // 2  # center horizontally
        y = 0  # from top
    else:
        # Original is too tall → crop vertically
        cropW = ow
        cropH = int(ow / target_ratio)
        x = 0
        y = 0  # from top (not centered vertically)

    cropped = pixmap.copy(x, y, cropW, cropH)

    return cropped.scaled(targetSize, mode=Qt.TransformationMode.SmoothTransformation)


def sortedNumerically(input: Iterable[str]) -> List[str]:
    def repl(num):
        return f"{int(num[0]):010d}"

    return sorted(input, key=lambda i: re.sub(r"(\d+)", repl, i))
