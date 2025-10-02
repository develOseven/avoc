import os
import json
import re

from typing import Iterable, List

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QDragMoveEvent, QDropEvent, QPalette, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QLabel, QListView, QListWidget, QListWidgetItem, QVBoxLayout, QWidget


VOICE_CARD_SIZE = QSize(188, 262)

DROP_MODEL_FILES = "Drop model files here<br><b>*.pth</b> and <b>*.index</b><br>OR<br><b>*.onnx</b><br><br>"
DROP_ICON_FILE = "Drop icon file here<br><b>*.png</b>, <b>*.jpeg</b>, <b>*.gif</b>..."


class WindowAreaWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout()

        self.voiceCards = FlowContainerWithFixedLast()

        layout.addWidget(self.voiceCards, stretch=2)
        layout.addWidget(QLabel("I take 1/3 of the window height"), stretch=1)
        self.setLayout(layout)

        modelDirToModelIcon: dict[str, QWidget] = {}

        model_dir = "model_dir"

        for folder in os.listdir(model_dir):
            if os.path.isdir(os.path.join(model_dir, folder)):
                params_file_path = os.path.join(model_dir, folder, "params.json")
                if os.path.exists(params_file_path):
                    with open(params_file_path) as f:
                        params = json.load(f)
                        icon_file_name = params.get("iconFile", "")
                        if icon_file_name:
                            pixmap = QPixmap(icon_file_name)
                            label = QLabel(self)
                            label.setPixmap(cropCenterScalePixmap(pixmap, VOICE_CARD_SIZE))
                            modelDirToModelIcon[folder] = label

        for folder in sortedNumerically(modelDirToModelIcon):
            self.voiceCards.addWidget(modelDirToModelIcon[folder])

        self.voiceCards.addWidget(VoiceCardPlaceholderWidget(VOICE_CARD_SIZE), selectable=False)


class FlowContainer(QListWidget):
    def __init__(self):
        super().__init__()

        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)

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
        self.setSpacing(4)

    def addWidget(self, widget: QWidget, selectable: bool = True):
        item = QListWidgetItem()
        if not selectable:
            item.setFlags(item.flags() & ~(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled))
        self.addItem(item)
        item.setSizeHint(widget.sizeHint())
        self.setItemWidget(item, widget)

    def insertWidget(self, row: int, widget: QWidget):
        item = QListWidgetItem()
        self.insertItem(row, item)
        item.setSizeHint(widget.sizeHint())
        self.setItemWidget(item, widget)


class FlowContainerWithFixedLast(FlowContainer):
    def dragMoveEvent(self, event: QDragMoveEvent):
        """Forbid going past the last item which is the voice card placeholder."""
        row = self.indexAt(event.pos()).row()
        if row >= 0 and row < self.count() - 1:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent):
        super().dropEvent(event)
        # self.setDropIndicatorShown(False)
        # self.viewport().update()
        # self.setDropIndicatorShown(True)


class VoiceCardPlaceholderWidget(QWidget):
    def __init__(self, cardSize: QSize, parent: QWidget | None = None):
        super().__init__(parent)

        self.cardSize = cardSize
        self.setStyleSheet("border: 2px solid;")

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        dropHere = QLabel(DROP_MODEL_FILES + DROP_ICON_FILE)
        dropHere.setTextFormat(Qt.TextFormat.RichText)
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
        x = (ow - cropW) // 2   # center horizontally
        y = 0                    # from top
    else:
        # Original is too tall → crop vertically
        cropW = ow
        cropH = int(ow / target_ratio)
        x = 0
        y = 0  # from top (not centered vertically)

    cropped = pixmap.copy(x, y, cropW, cropH)

    return cropped.scaled(targetSize)


def sortedNumerically(input: Iterable[str]) -> List[str]:
    def repl(num):
        return f"{int(num[0]):010d}"

    return sorted(input, key=lambda i: re.sub(r'(\d+)', repl, i))
