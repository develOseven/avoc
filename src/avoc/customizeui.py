from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .audiobackends import HAS_PIPEWIRE

if HAS_PIPEWIRE:
    from .audiopipewiresettings import AudioPipeWireSettingsGroupBox
else:
    from .audioqtmultimediasettings import AudioQtMultimediaSettingsGroupBox

DEFAULT_CACHED_MODELS_COUNT = 1


class CustomizeUiWidget(QWidget):
    back = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        interfaceSettings = QSettings()
        interfaceSettings.beginGroup("InterfaceSettings")

        layout = QVBoxLayout()

        showNotificationsCheckBox = QCheckBox("Show Notifications")
        showNotificationsCheckBox.setChecked(
            bool(interfaceSettings.value("showNotifications", True))
        )
        showNotificationsCheckBox.toggled.connect(
            lambda checked: interfaceSettings.setValue("showNotifications", checked)
        )

        layout.addWidget(showNotificationsCheckBox)

        cachedModelsCountlayout = QHBoxLayout()

        cachedModelsCountLabel = QLabel("Models to Cache")
        cachedModelsCountLabel.setToolTip(
            "Number of voice cards to cache for fast switching."
        )
        cachedModelsCountlayout.addWidget(cachedModelsCountLabel)

        cachedModelsCountSpinBox = QSpinBox(minimum=1, maximum=256)
        cachedModelsCount = interfaceSettings.value(
            "cachedModelsCount", DEFAULT_CACHED_MODELS_COUNT, type=int
        )
        assert type(cachedModelsCount) is int
        cachedModelsCountSpinBox.setValue(cachedModelsCount)
        cachedModelsCountSpinBox.valueChanged.connect(
            lambda cachedModelsCount: interfaceSettings.setValue(
                "cachedModelsCount", cachedModelsCount
            )
        )
        cachedModelsCountlayout.addWidget(cachedModelsCountSpinBox)

        if HAS_PIPEWIRE:
            self.audioPipeWireSettingsGroupBox = AudioPipeWireSettingsGroupBox()
            layout.addWidget(self.audioPipeWireSettingsGroupBox)
        else:
            self.audioQtMultimediaSettingsGroupBox = AudioQtMultimediaSettingsGroupBox()
            layout.addWidget(self.audioQtMultimediaSettingsGroupBox)

        cachedModelsCountlayout.addStretch()

        layout.addLayout(cachedModelsCountlayout)

        self.backButton = QPushButton("Back")
        self.backButton.clicked.connect(lambda: self.back.emit())
        layout.addWidget(self.backButton)

        layout.addStretch()

        self.setLayout(layout)
