from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QCheckBox, QGridLayout, QGroupBox, QWidget


class AudioPipeWireSettingsGroupBox(QGroupBox):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.setTitle("Audio PipeWire Settings")

        settings = QSettings()
        settings.beginGroup("AudioPipeWireSettings")

        audioSettingsLayout = QGridLayout()
        audioSettingsLayout.setColumnStretch(1, 1)  # Stretch the comboboxes.
        row = 0
        self.autoLinkCheckBox = QCheckBox("Auto-Link Apps to the Voice Changer")
        self.autoLinkCheckBox.setToolTip(
            "Use voice changer audio for the recording apps."
        )
        self.autoLinkCheckBox.setChecked(bool(settings.value("autoLink", True)))
        self.autoLinkCheckBox.toggled.connect(
            lambda checked: settings.setValue("autoLink", checked)
        )
        audioSettingsLayout.addWidget(self.autoLinkCheckBox, row, 1)

        self.setLayout(audioSettingsLayout)
