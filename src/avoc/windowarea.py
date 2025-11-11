import os
import re
from typing import Iterable, List

from PySide6.QtCore import QModelIndex, QSettings, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
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
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from voiceconversion.utils.import_model_params import (
    ImportModelParamFile,
    ImportModelParams,
)

from .exceptions import FailedToMoveVoiceCardException
from .modelsettings import ModelSettingsGroupBox
from .processingsettings import ProcessingSettingsGroupBox
from .voicecardsmanager import VoiceCardsManager

VOICE_CARD_SIZE = QSize(188, 262)
VOICE_CARD_MARGIN = 8

UNKNOWN_MODEL_NAME = "Unknown Model"
DROP_MODEL_FILES = "Drop model files here<br><b>*.pth</b> and <b>*.index</b><br><br>"
DROP_ICON_FILE = "Drop icon file here<br><b>*.png</b>, <b>*.jpeg</b>, <b>*.gif</b>..."
START_TXT = "Start"
RUNNING_TXT = "Running..."
PASS_THROUGH_TXT = "Pass Through"


class WindowAreaWidget(QWidget):
    cardMoved = Signal(int, int)
    cardsRemoved = Signal(int, int)

    def __init__(
        self,
        voiceCardsManager: VoiceCardsManager,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        settings = QSettings()
        settings.beginGroup("InterfaceSettings")

        layout = QVBoxLayout()

        self.voiceCards = VoiceCardsContainer(voiceCardsManager)

        layout.addWidget(self.voiceCards, stretch=2)

        controlsLayout = QHBoxLayout()

        self.processingSettingsGroupBox = ProcessingSettingsGroupBox()
        controlsLayout.addWidget(self.processingSettingsGroupBox, stretch=1)

        self.modelSettingsGroupBox = ModelSettingsGroupBox()
        controlsLayout.addWidget(self.modelSettingsGroupBox, stretch=1)

        buttonsLayout = QVBoxLayout()

        self.startButton = QToolButton(
            toolButtonStyle=Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.startButton.setText(START_TXT)
        fm = QFontMetrics(self.startButton.font())
        maxButtonWidth = int(
            max(
                fm.horizontalAdvance(t)
                for t in [START_TXT, RUNNING_TXT, PASS_THROUGH_TXT]
            )
            * 1.618
        )
        # Make the Start button size fixed.
        self.startButton.setMinimumWidth(maxButtonWidth)
        # Make the Start button toggle and change text when clicked.
        self.startButton.setCheckable(True)
        self.startButton.toggled.connect(
            lambda checked: self.startButton.setText(
                RUNNING_TXT if checked else START_TXT
            )
        )
        # Can't change processing settings while running.
        self.startButton.toggled.connect(
            lambda checked: self.processingSettingsGroupBox.setEnabled(not checked)
        )
        buttonsLayout.addWidget(self.startButton)

        self.passThroughButton = QToolButton(
            toolButtonStyle=Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.passThroughButton.setText(PASS_THROUGH_TXT)
        self.passThroughButton.setMinimumWidth(maxButtonWidth)
        self.passThroughButton.setCheckable(True)
        buttonsLayout.addWidget(self.passThroughButton)

        controlsLayout.addLayout(buttonsLayout)

        layout.addLayout(controlsLayout, stretch=1)

        self.setLayout(layout)

        for voiceCardIndex in range(voiceCardsManager.count()):
            self.voiceCards.addVoiceCard(
                self.voiceCards.voiceCardForIndex(voiceCardIndex)
            )

        self.voiceCards.addVoiceCard(
            VoiceCardPlaceholderWidget(
                VOICE_CARD_SIZE, DROP_MODEL_FILES + DROP_ICON_FILE
            ),
            selectable=False,
        )

        self.voiceCards.model().rowsMoved.connect(self.onCardsMoved)
        self.voiceCards.model().rowsRemoved.connect(self.onCardsRemoved)
        self.voiceCards.model().rowsRemoved.connect(
            lambda _, first, last: settings.setValue(
                "currentVoiceCardIndex",
                (
                    last
                    if settings.value("currentVoiceCardIndex", 0) > last
                    else settings.value("currentVoiceCardIndex", 0)
                ),
            )
        )

        def onRowsInserted(_: QModelIndex, first: int, last: int):
            if last - first + 1 == self.voiceCards.count() - 1:  # minus the placeholder
                self.voiceCards.setCurrentRow(
                    int(settings.value("currentVoiceCardIndex", 0))
                )

        # QueuedConnection to make sure that the widget is properly set into the card.
        self.voiceCards.model().rowsInserted.connect(
            onRowsInserted, type=Qt.ConnectionType.QueuedConnection
        )

        self.voiceCards.setCurrentRow(int(settings.value("currentVoiceCardIndex", 0)))
        self.voiceCards.currentRowChanged.connect(
            lambda row: settings.setValue("currentVoiceCardIndex", row)
        )

        # Disable the start button if there are no voice cards.
        self.voiceCards.currentRowChanged.connect(
            lambda row: self.startButton.setEnabled(row >= 0)
        )
        self.startButton.setEnabled(self.voiceCards.currentRow() >= 0)

    def onCardsMoved(
        self,
        sourceParent: QModelIndex,
        sourceStart: int,
        sourceEnd: int,
        destinationParent: QModelIndex,
        destinationRow: int,
    ):
        if sourceStart != sourceEnd:
            raise FailedToMoveVoiceCardException

        self.cardMoved.emit(sourceStart, destinationRow)

    def onCardsRemoved(self, parent: QModelIndex, first: int, last: int):
        self.cardsRemoved.emit(first, last)


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

    droppedModelFiles = Signal(int, ImportModelParams)
    droppedIconFile = Signal(int, str)

    def __init__(self, voiceCardsManager: VoiceCardsManager):
        super().__init__()
        self.voiceCardsManager = voiceCardsManager

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

        row = self.indexAt(event.position().toPoint()).row()
        importingNew = row < 0 or row >= self.count()
        voiceCardIndex = self.count() - 1 if importingNew else row

        if len(indexFiles) == 1:
            self.droppedModelFiles.emit(
                voiceCardIndex,
                ImportModelParams(
                    voice_changer_type="RVC",
                    files=[
                        ImportModelParamFile(
                            name=pthFiles[0].toLocalFile(), kind="rvcModel", dir=""
                        ),
                        ImportModelParamFile(
                            name=indexFiles[0].toLocalFile(), kind="rvcIndex", dir=""
                        ),
                    ],
                    params={},
                ),
            )

        if len(iconFiles) == 1 and voiceCardIndex < self.count() - 1:
            self.droppedIconFile.emit(voiceCardIndex, iconFiles[0].toLocalFile())

        event.acceptProposedAction()

    def setVoiceCardContextMenu(self, item: QListWidgetItem, widget: QWidget):
        contextMenu = QMenu(widget)
        contextMenu.setObjectName("VoiceCardPopUpMenu")
        deleteAction = QAction("Delete", widget)
        deleteAction.setObjectName("Delete")
        deleteAction.triggered.connect(lambda: self.takeItem(self.row(item)))
        contextMenu.addAction(deleteAction)
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(
            lambda point: contextMenu.exec(widget.mapToGlobal(point))
        )

    def addVoiceCard(self, widget: QWidget, selectable: bool = True):
        item = QListWidgetItem()
        if not selectable:
            item.setFlags(
                item.flags()
                & ~(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            )
        self.addItem(item)
        item.setSizeHint(widget.sizeHint())
        self.setItemWidget(item, widget)
        if selectable:
            self.setVoiceCardContextMenu(item, widget)

    def insertVoiceCard(self, row: int, widget: QWidget):
        item = QListWidgetItem()
        self.insertItem(row, item)
        item.setSizeHint(widget.sizeHint())
        self.setItemWidget(item, widget)
        self.setVoiceCardContextMenu(item, widget)

    def onVoiceCardUpdated(self, row: int):
        widget = self.voiceCardForIndex(row)

        if row >= self.count() - 1:
            item = self.insertVoiceCard(row, widget)
        else:
            item = self.item(row)
            self.setItemWidget(item, widget)
            self.setVoiceCardContextMenu(item, widget)

    def voiceCardForIndex(self, row: int) -> QWidget:
        widget: QWidget | QLabel | None = None
        name = UNKNOWN_MODEL_NAME
        importedModelInfo = self.voiceCardsManager.get(row)
        if importedModelInfo is not None:
            name = importedModelInfo.name
            iconFile = self.voiceCardsManager.getIcon(row)
            if iconFile is not None:
                pixmap = QPixmap(iconFile)
                widget = QLabel()
                widget.setPixmap(cropCenterScalePixmap(pixmap, VOICE_CARD_SIZE))
                widget.setToolTip(name)
        if widget is None:
            widget = VoiceCardPlaceholderWidget(
                VOICE_CARD_SIZE, f"{name}<br><br>{DROP_ICON_FILE}"
            )
        widget.setToolTip(name)
        return widget


class VoiceCardPlaceholderWidget(QWidget):
    def __init__(self, cardSize: QSize, text: str, parent: QWidget | None = None):
        super().__init__(parent)

        self.cardSize = cardSize
        self.setStyleSheet("border: 2px solid;")

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        dropHere = QLabel(text)
        dropHere.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        dropHere.setTextFormat(Qt.TextFormat.RichText)
        dropHere.setWordWrap(True)
        dropHere.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(dropHere)
        self.setLayout(layout)

    def sizeHint(self):
        return self.cardSize

    def pixmap(self) -> QPixmap | None:
        return None


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
