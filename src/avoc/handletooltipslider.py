from typing import Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractSlider,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QToolTip,
)


class HandleToolTipSlider(QSlider):
    def __init__(
        self,
        orientation=Qt.Orientation.Horizontal,
        formatToolTip=Callable[[int], str],
        parent=None,
    ):
        super().__init__(orientation, parent)
        self.formatToolTip = formatToolTip

    def sliderHandleRect(self):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)

        return self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            opt,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )

    def showSliderHandleToolTip(self):
        QToolTip.showText(
            self.mapToGlobal(self.sliderHandleRect().bottomLeft()),
            self.formatToolTip(self.value()),
            self,
        )

    def sliderChange(self, change):
        super().sliderChange(change)

        if change == QAbstractSlider.SliderChange.SliderValueChange:
            self.showSliderHandleToolTip()

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip:
            shr = self.sliderHandleRect()
            if shr.contains(event.pos()):
                self.showSliderHandleToolTip()
            else:
                QToolTip.hideText()
                event.ignore()
            return True

        return super().event(event)
