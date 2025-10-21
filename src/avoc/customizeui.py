from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import QCheckBox, QPushButton, QVBoxLayout, QWidget


class CustomizeUiWidget(QWidget):
    back = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        interfaceSettings = QSettings()
        interfaceSettings.beginGroup("Interface")

        layout = QVBoxLayout()

        self.showNotificationsCheckBox = QCheckBox("Show Notifications")
        self.showNotificationsCheckBox.setChecked(
            bool(interfaceSettings.value("showNotifications", True))
        )
        self.showNotificationsCheckBox.toggled.connect(
            lambda checked: interfaceSettings.setValue("showNotifications", checked)
        )

        layout.addWidget(self.showNotificationsCheckBox)

        self.backButton = QPushButton("Back")
        self.backButton.clicked.connect(lambda: self.back.emit())
        layout.addWidget(self.backButton)

        layout.addStretch()

        self.setLayout(layout)
