from PySide6.QtGui import QAction
from PySide6.QtWidgets import QCheckBox, QWidget


class ActionCheckBox(QCheckBox):
    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self._action: QAction | None = None
        self._updating = False  # guard against recursion

        self.toggled.connect(self._onToggledByUser)

    def action(self) -> QAction | None:
        return self._action

    def setDefaultAction(self, action: QAction | None) -> None:
        if action is self._action:
            return

        if self._action is not None:
            self._action.changed.disconnect(self._onActionChanged)
            self._action.toggled.disconnect(self._onActionToggled)

        self._action = action

        if action is None:
            return

        self._syncFromAction()

        action.changed.connect(self._onActionChanged)
        action.toggled.connect(self._onActionToggled)

    def _syncFromAction(self) -> None:
        if self._action is None:
            return

        self._updating = True
        try:
            oldBlockSignalsState = self.blockSignals(True)
            self.setChecked(self._action.isChecked())
            self.blockSignals(oldBlockSignalsState)
        finally:
            self._updating = False

    def _onToggledByUser(self, checked: bool) -> None:
        if self._action is None:
            return

        self._action.setChecked(checked)

    def _onActionChanged(self) -> None:
        if self._updating:
            return
        self._syncFromAction()

    def _onActionToggled(self, checked: bool) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            oldBlockSignalsState = self.blockSignals(True)
            self.setChecked(checked)
            self.blockSignals(oldBlockSignalsState)
        finally:
            self._updating = False
