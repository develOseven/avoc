from typing import Tuple, get_args

from PySide6.QtCore import QEvent, QPoint, QSettings, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QSlider,
    QSpinBox,
    QWidget,
)
from voiceconversion.common.deviceManager.DeviceManager import (
    DeviceManager,
    DevicePresentation,
)
from voiceconversion.const import PitchExtractorType

from .handletooltipslider import HandleToolTipSlider

F0_DET_PREFERENCES = [
    "rmvpe_onnx",
    "rmvpe",
    "crepe_full_onnx",
    "crepe_full",
    "crepe_tiny_onnx",
    "crepe_tiny",
    "fcpe_onnx",
    "fcpe",
]
BACKEND_PREFERENCES = ["cuda", "directml", "mps", "cpu"]
DEFAULT_SILENT_THRESHOLD = -90
DEFAULT_CHUNK_SIZE = 16
DEFAULT_EXTRA_CONVERT_SIZE = 3.0

DEFAULT_SAMPLE_RATE = 48000
SAMPLE_RATES = [
    32000,
    44100,
    48000,
    96000,
    128000,
]


def getF0DetByPreference() -> list[str]:
    return sorted(
        get_args(PitchExtractorType),
        key=lambda d: (
            F0_DET_PREFERENCES.index(d)
            if d in F0_DET_PREFERENCES
            else len(F0_DET_PREFERENCES)
        ),
    )


def loadF0Det() -> Tuple[int, list[str]]:
    """:return: f0 detector index and the list of all"""
    processingSettings = QSettings()
    processingSettings.beginGroup("ProcessingSettings")
    f0DetByPreference = getF0DetByPreference()
    f0Det = processingSettings.value("f0Det", f0DetByPreference[0], type=str)
    assert type(f0Det) is str
    try:
        index = f0DetByPreference.index(f0Det)
    except ValueError:
        index = 0
    return index, f0DetByPreference


def loadGpu() -> Tuple[int, DevicePresentation]:
    """:return: GPU index (not id) from settings, all devices sorted by preference"""
    processingSettings = QSettings()
    processingSettings.beginGroup("ProcessingSettings")
    devicesByPreference = sorted(
        DeviceManager.list_devices(),
        key=lambda d: (
            BACKEND_PREFERENCES.index(d["backend"])
            if d["backend"] in BACKEND_PREFERENCES
            else len(BACKEND_PREFERENCES)
        ),
    )
    gpu = processingSettings.value("gpu", devicesByPreference[0]["name"], type=str)
    assert type(gpu) is str
    try:
        index = next(i for i, d in enumerate(devicesByPreference) if d["name"] == gpu)
    except StopIteration:
        index = 0
    return index, devicesByPreference


def loadSampleRate() -> Tuple[int, int]:
    """:return: sample rate and its index in the SAMPLE_RATES list"""
    processingSettings = QSettings()
    processingSettings.beginGroup("ProcessingSettings")
    savedSampleRate = processingSettings.value(
        "sampleRate", DEFAULT_SAMPLE_RATE, type=int
    )
    assert type(savedSampleRate) is int
    try:
        index = SAMPLE_RATES.index(savedSampleRate)
    except IndexError:
        index = DEFAULT_SAMPLE_RATE
    return SAMPLE_RATES[index], index


class ProcessingSettingsGroupBox(QGroupBox):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.setTitle("Processing Settings")

        processingSettingsLayout = QGridLayout()
        row = 0
        f0DetLabel = QLabel("F0 Detector")
        f0DetLabel.setToolTip("A pitch extraction algorithm.")
        self.f0DetComboBox = QComboBox()
        f0DetIndex, f0DetByPreference = loadF0Det()
        self.f0DetComboBox.addItems(f0DetByPreference)
        processingSettingsLayout.addWidget(f0DetLabel, row, 0)
        processingSettingsLayout.addWidget(self.f0DetComboBox, row, 1, 1, 2)
        row += 1
        silentThresholdLabel = QLabel("Input sensitivity")
        silentThresholdLabel.setToolTip(
            "The input volume required to activate the voice changer."
        )
        silentThresholdSlider = QSlider(Qt.Orientation.Horizontal)
        self.silentThresholdSpinBox = QSpinBox(minimum=-90, maximum=-60)
        silentThresholdSlider.setMinimum(self.silentThresholdSpinBox.minimum())
        silentThresholdSlider.setMaximum(self.silentThresholdSpinBox.maximum())
        silentThresholdSlider.valueChanged.connect(
            lambda v: self.silentThresholdSpinBox.setValue(v)
        )
        self.silentThresholdSpinBox.valueChanged.connect(
            lambda v: silentThresholdSlider.setValue(v)
        )
        processingSettingsLayout.addWidget(silentThresholdLabel, row, 0)
        processingSettingsLayout.addWidget(silentThresholdSlider, row, 1)
        processingSettingsLayout.addWidget(self.silentThresholdSpinBox, row, 2)
        row += 1
        chunkSizeLabel = QLabel("Chunk Size")
        chunkSizeLabel.setToolTip(
            "Controls the delay and GPU usage. Bigger chunk - more delay, less GPU usage. Smaller chunk - vice versa."  # noqa: E501
        )
        chunkSizeSlider = HandleToolTipSlider(
            Qt.Orientation.Horizontal,
            formatToolTip=lambda v: f"{v*128*1000/loadSampleRate()[0]:.2f} ms",
        )
        self.chunkSizeSpinBox = QSpinBox(minimum=8, maximum=256, singleStep=8)

        def onChunkSizeSpinBoxEditingFinished():
            step = self.chunkSizeSpinBox.singleStep()
            value = self.chunkSizeSpinBox.value()
            self.chunkSizeSpinBox.setValue((value // step) * step)

        self.chunkSizeSpinBox.editingFinished.connect(onChunkSizeSpinBoxEditingFinished)

        chunkSizeSlider.setMinimum(self.chunkSizeSpinBox.minimum() // 8)
        chunkSizeSlider.setMaximum(self.chunkSizeSpinBox.maximum() // 8)
        chunkSizeSlider.valueChanged.connect(
            lambda v: self.chunkSizeSpinBox.setValue(v * 8)
        )
        self.chunkSizeSpinBox.valueChanged.connect(
            lambda v: chunkSizeSlider.setValue(v // 8)
        )
        processingSettingsLayout.addWidget(chunkSizeLabel, row, 0)
        processingSettingsLayout.addWidget(chunkSizeSlider, row, 1)
        processingSettingsLayout.addWidget(self.chunkSizeSpinBox, row, 2)
        row += 1
        extraConvertSizeLabel = QLabel("Extra")
        extraConvertSizeLabel.setToolTip(
            "Extra audio history that will be used for voice conversion. Does not affect the delay. More extra - better voice quality, more GPU usage. Less extra - vice versa."  # noqa: E501
        )
        extraConvertSizeSlider = QSlider(
            Qt.Orientation.Horizontal,
        )
        self.extraConvertSizeDoubleSpinBox = QDoubleSpinBox(
            minimum=0.1, maximum=5, singleStep=0.1, decimals=1
        )
        extraConvertSizeSlider.setMinimum(
            int(self.extraConvertSizeDoubleSpinBox.minimum() * 10)
        )
        extraConvertSizeSlider.setMaximum(
            int(self.extraConvertSizeDoubleSpinBox.maximum() * 10)
        )
        extraConvertSizeSlider.valueChanged.connect(
            lambda v: self.extraConvertSizeDoubleSpinBox.setValue(v / 10.0)
        )
        self.extraConvertSizeDoubleSpinBox.valueChanged.connect(
            lambda v: extraConvertSizeSlider.setValue(v * 10)
        )
        processingSettingsLayout.addWidget(extraConvertSizeLabel, row, 0)
        processingSettingsLayout.addWidget(extraConvertSizeSlider, row, 1)
        processingSettingsLayout.addWidget(self.extraConvertSizeDoubleSpinBox, row, 2)
        row += 1
        gpuLabel = QLabel("Computing Device")
        gpuLabel.setToolTip(
            "A device like a GPU (Graphics Processing Unit) to use for the voice conversion."  # noqa: E501
        )
        self.gpuComboBox = QComboBox()
        gpuIndex, devicesByPreference = loadGpu()
        self.gpuComboBox.addItems([d["name"] for d in devicesByPreference])
        processingSettingsLayout.addWidget(gpuLabel, row, 0)
        processingSettingsLayout.addWidget(self.gpuComboBox, row, 1, 1, 2)
        row += 1
        self.sampleRateComboBox = QComboBox()
        processingSettingsLayout.addWidget(QLabel("Sample Rate"), row, 0)
        processingSettingsLayout.addWidget(self.sampleRateComboBox, row, 1, 1, 2)

        self.setLayout(processingSettingsLayout)

        # Restore from saved settings.

        processingSettings = QSettings()
        processingSettings.beginGroup("ProcessingSettings")

        self.f0DetComboBox.setCurrentIndex(f0DetIndex)

        self.f0DetComboBox.currentTextChanged.connect(
            lambda text: processingSettings.setValue("f0Det", text)
        )

        silentThreshold = processingSettings.value(
            "silentThreshold", DEFAULT_SILENT_THRESHOLD, type=int
        )
        assert type(silentThreshold) is int
        self.silentThresholdSpinBox.setValue(silentThreshold)

        self.silentThresholdSpinBox.valueChanged.connect(
            lambda silentThreshold: processingSettings.setValue(
                "silentThreshold", silentThreshold
            )
        )

        chunkSize = processingSettings.value("chunkSize", DEFAULT_CHUNK_SIZE, type=int)
        assert type(chunkSize) is int
        self.chunkSizeSpinBox.setValue(chunkSize)

        self.chunkSizeSpinBox.valueChanged.connect(
            lambda chunkSize: processingSettings.setValue("chunkSize", chunkSize)
        )

        extraConvertSize = processingSettings.value(
            "extraConvertSize", DEFAULT_EXTRA_CONVERT_SIZE, type=float
        )
        assert type(extraConvertSize) is float
        self.extraConvertSizeDoubleSpinBox.setValue(extraConvertSize)

        self.extraConvertSizeDoubleSpinBox.valueChanged.connect(
            lambda extraConvertSize: processingSettings.setValue(
                "extraConvertSize", extraConvertSize
            )
        )

        self.gpuComboBox.setCurrentIndex(gpuIndex)

        self.gpuComboBox.currentTextChanged.connect(
            lambda text: processingSettings.setValue("gpu", text)
        )

        for sampleRate in SAMPLE_RATES:
            self.sampleRateComboBox.addItem(str(sampleRate))

        _, index = loadSampleRate()
        self.sampleRateComboBox.setCurrentIndex(index)

        self.sampleRateComboBox.currentIndexChanged.connect(
            lambda: processingSettings.setValue(
                "sampleRate", int(self.sampleRateComboBox.currentText())
            ),
        )
