from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QSlider,
    QSpinBox,
    QWidget,
)


class ModelSettingsGroupBox(QGroupBox):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.setTitle("Active Voice Model Settings")

        modelSettingsLayout = QGridLayout()
        row = 0
        pitchLabel = QLabel("Pitch")
        pitchLabel.setToolTip(
            "Pitch shift alters the tone of voice. If your voice is low-pitched (f.e., male voice) and model is high-pitched (f.e., a female voice model), increase this setting (i.e., set to 12). Otherwise, decrease this setting (i.e., set to -12)."  # noqa: E501
        )
        pitchSlider = QSlider(Qt.Orientation.Horizontal)
        self.pitchSpinBox = QSpinBox(minimum=-50, maximum=50)
        pitchSlider.setMinimum(self.pitchSpinBox.minimum())
        pitchSlider.setMaximum(self.pitchSpinBox.maximum())
        pitchSlider.valueChanged.connect(lambda v: self.pitchSpinBox.setValue(v))
        self.pitchSpinBox.valueChanged.connect(lambda v: pitchSlider.setValue(v))
        self.pitchSpinBox.valueChanged.connect(lambda: self.changed.emit())
        modelSettingsLayout.addWidget(pitchLabel, row, 0)
        modelSettingsLayout.addWidget(pitchSlider, row, 1)
        modelSettingsLayout.addWidget(self.pitchSpinBox, row, 2)
        row += 1
        formantShiftLabel = QLabel("Formant Shift")
        formantShiftLabel.setToolTip(
            "Formant shift alters harmonic frequencies and changes the voice timbre without affecting the pitch."  # noqa: E501
        )
        formantShiftSlider = QSlider(Qt.Orientation.Horizontal)
        self.formantShiftDoubleSpinBox = QDoubleSpinBox(
            minimum=-5, maximum=5, singleStep=0.1, decimals=1
        )
        formantShiftSlider.setMinimum(
            int(self.formantShiftDoubleSpinBox.minimum() * 10)
        )
        formantShiftSlider.setMaximum(
            int(self.formantShiftDoubleSpinBox.maximum() * 10)
        )
        formantShiftSlider.valueChanged.connect(
            lambda v: self.formantShiftDoubleSpinBox.setValue(v / 10.0)
        )
        self.formantShiftDoubleSpinBox.valueChanged.connect(
            lambda v: formantShiftSlider.setValue(v * 10)
        )
        self.formantShiftDoubleSpinBox.valueChanged.connect(lambda: self.changed.emit())
        modelSettingsLayout.addWidget(formantShiftLabel, row, 0)
        modelSettingsLayout.addWidget(formantShiftSlider, row, 1)
        modelSettingsLayout.addWidget(self.formantShiftDoubleSpinBox, row, 2)
        row += 1
        indexLabel = QLabel("Index")
        indexLabel.setToolTip(
            "Index embeds accent of the model's voice into your voice. Disabled when set to 0. Note that this setting increases CPU usage."  # noqa: E501
        )
        indexSlider = QSlider(Qt.Orientation.Horizontal)
        self.indexDoubleSpinBox = QDoubleSpinBox(
            minimum=0, maximum=1, singleStep=0.1, decimals=1
        )
        indexSlider.setMinimum(int(self.indexDoubleSpinBox.minimum() * 10))
        indexSlider.setMaximum(int(self.indexDoubleSpinBox.maximum() * 10))
        indexSlider.valueChanged.connect(
            lambda v: self.indexDoubleSpinBox.setValue(v / 10.0)
        )
        self.indexDoubleSpinBox.valueChanged.connect(
            lambda v: indexSlider.setValue(v * 10)
        )
        self.indexDoubleSpinBox.valueChanged.connect(lambda: self.changed.emit())
        modelSettingsLayout.addWidget(indexLabel, row, 0)
        modelSettingsLayout.addWidget(indexSlider, row, 1)
        modelSettingsLayout.addWidget(self.indexDoubleSpinBox, row, 2)

        self.setLayout(modelSettingsLayout)
