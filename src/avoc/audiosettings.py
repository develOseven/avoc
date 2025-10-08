from PySide6.QtCore import QByteArray, QSettings
from PySide6.QtWidgets import QComboBox, QGridLayout, QGroupBox, QLabel, QWidget

from .audiodevices import getAudioDevicesForSampleRate

DEFAULT_SAMPLE_RATE = 48000
SAMPLE_RATES = (
    32000,
    44100,
    48000,
    96000,
    128000,
)  # TODO: 44100 leads to crashes because the algo resamples to 16k badly


class AudioSettingsGroupBox(QGroupBox):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.setTitle("Audio Settings")

        audioSettingsLayout = QGridLayout()
        audioSettingsLayout.setColumnStretch(1, 1)  # Stretch the comboboxes.
        row = 0
        self.sampleRateComboBox = QComboBox()
        audioSettingsLayout.addWidget(QLabel("Sample Rate"), row, 0)
        audioSettingsLayout.addWidget(self.sampleRateComboBox, row, 1)
        row += 1
        self.audioInputComboBox = AudioDevicesComboBox(isInput=True)
        self.audioInputComboBox.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        audioSettingsLayout.addWidget(QLabel("Audio Input"), row, 0)
        audioSettingsLayout.addWidget(self.audioInputComboBox, row, 1)
        row += 1
        self.audioOutputComboBox = AudioDevicesComboBox(isInput=False)
        self.audioOutputComboBox.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        audioSettingsLayout.addWidget(QLabel("Audio Output"), row, 0)
        audioSettingsLayout.addWidget(self.audioOutputComboBox, row, 1)

        self.setLayout(audioSettingsLayout)

        settings = QSettings()
        settings.beginGroup("AudioSettings")

        # Restore the sample rate from saved settings.
        for sampleRate in SAMPLE_RATES:
            self.sampleRateComboBox.addItem(str(sampleRate))

        savedSampleRate = settings.value("sampleRate", DEFAULT_SAMPLE_RATE)
        index = (
            self.sampleRateComboBox.findText(str(savedSampleRate))
            if savedSampleRate is not None
            else -1
        )
        if index >= 0:
            self.sampleRateComboBox.setCurrentIndex(index)
        else:
            self.sampleRateComboBox.setCurrentIndex(
                SAMPLE_RATES.index(DEFAULT_SAMPLE_RATE)
            )

        self.sampleRateComboBox.currentIndexChanged.connect(
            lambda index: self.audioInputComboBox.refreshDeviceOptions(
                SAMPLE_RATES[index]
            ),
            self.audioOutputComboBox.refreshDeviceOptions(SAMPLE_RATES[index]),
        )

        # Load the device lists.
        self.audioInputComboBox.refreshDeviceOptions(
            self.sampleRateComboBox.currentIndex()
        )
        self.audioOutputComboBox.refreshDeviceOptions(
            self.sampleRateComboBox.currentIndex()
        )

        # Restore the input device from saved settings.
        self.audioInputComboBox.restoreFromSavedSetting(
            settings.value("audioInputDevice")
        )
        self.audioOutputComboBox.restoreFromSavedSetting(
            settings.value("audioOutputDevice")
        )

        # Set up the saving of the settings.
        self.sampleRateComboBox.currentIndexChanged.connect(
            lambda: settings.setValue(
                "sampleRate", int(self.sampleRateComboBox.currentText())
            ),
        )
        self.audioInputComboBox.currentIndexChanged.connect(
            lambda: settings.setValue(
                "audioInputDevice", self.audioInputComboBox.currentData()
            ),
        )
        self.audioOutputComboBox.currentIndexChanged.connect(
            lambda: settings.setValue(
                "audioOutputDevice", self.audioOutputComboBox.currentData()
            ),
        )

        # Sync settings in case they weren't initialized.
        settings.setValue("sampleRate", int(self.sampleRateComboBox.currentText()))
        settings.setValue("audioInputDevice", self.audioInputComboBox.currentData())
        settings.setValue("audioOutputDevice", self.audioOutputComboBox.currentData())


class AudioDevicesComboBox(QComboBox):
    def __init__(self, isInput: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.isInput = isInput
        self.defaultIndex = 0

    def refreshDeviceOptions(self, sampleRate: int):
        audioDevices = getAudioDevicesForSampleRate(sampleRate, self.isInput)
        if sorted(audioDevices.keys()) != sorted(
            [self.itemData(i) for i in range(self.count())]
        ):
            self.clear()
            index = 0
            for id, (description, isDefault) in audioDevices.items():
                self.addItem(description, id)
                if isDefault:
                    self.defaultIndex = index
                index += 1

    def restoreFromSavedSetting(self, id: QByteArray | None):
        index = self.findData(id) if id is not None else -1
        self.setCurrentIndex(index if index >= 0 else self.defaultIndex)
