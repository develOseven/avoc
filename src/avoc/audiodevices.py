from PySide6.QtCore import QByteArray
from PySide6.QtMultimedia import QAudioFormat, QMediaDevices


def getAudioDevicesForSampleRate(
    sampleRate: int, isInput: bool
) -> dict[QByteArray, (str, bool)]:
    """Return compatible devices: id, readable name, a flag if it's the default device."""

    if isInput:
        audioDevices = QMediaDevices.audioInputs()
    else:
        audioDevices = QMediaDevices.audioOutputs()

    format = QAudioFormat()
    format.setSampleRate(sampleRate)
    format.setChannelCount(1)
    format.setSampleFormat(QAudioFormat.SampleFormat.Float)

    return {
        d.id(): (d.description(), d.isDefault())
        for d in audioDevices
        if d.isFormatSupported(format)
    }
