# https://github.com/KubaO/stackoverflown/tree/master/questions/overlay-widget-19362455
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QResizeEvent
from PySide6.QtWidgets import QWidget


class OverlayWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._new_parent()

    def _new_parent(self):
        """Install event filter and raise over parent's children."""
        if not self.parent():
            return
        self.parent().installEventFilter(self)
        self.raise_()

    def eventFilter(self, obj, event):
        """Catch resize and child-added events from parent."""
        if obj == self.parent():
            if event.type() == QEvent.Resize:
                self.resize(event.size())
            elif event.type() == QEvent.ChildAdded:
                self.raise_()
        return super().eventFilter(obj, event)

    def event(self, event):
        """Track parent changes."""
        if event.type() == QEvent.ParentAboutToChange:
            if self.parent():
                self.parent().removeEventFilter(self)
        elif event.type() == QEvent.ParentChange:
            self._new_parent()
        return super().event(event)


class LoadingOverlay(OverlayWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, event):
        """Paint semi-transparent overlay with loading text."""
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(100, 100, 100, 128))
        p.setPen(QColor(200, 200, 200))
        p.setFont(QFont("Arial", 48))
        p.drawText(self.rect(), Qt.AlignHCenter | Qt.AlignVCenter, "Loading...")
