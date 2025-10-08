import numpy as np
from PySide6.QtCore import QByteArray, QIODevice
from PySide6.QtMultimedia import (
    QAudioDevice,
    QAudioFormat,
    QAudioSink,
    QAudioSource,
    QMediaDevices,
)

from .exceptions import AudioDeviceDisappearedException


class AudioFilter(QIODevice):
    def __init__(
        self, inputDevice: QIODevice, blockSamplesCount: int, changeVoice, parent=None
    ):
        super().__init__(parent)

        self.inputDevice = inputDevice
        self.inputDevice.readyRead.connect(self.onReadyRead)
        self.changeVoice = changeVoice
        self.audioInBuff = np.empty(0, dtype=np.float32)
        self.blockSamplesCount = blockSamplesCount

    def readData(self, maxlen: int) -> object:
        data: QByteArray = self.inputDevice.read(maxlen)

        result = np.empty(0, dtype=np.float32)

        self.audioInBuff = np.append(
            self.audioInBuff, np.frombuffer(bytes(data), dtype=np.float32)
        )

        while len(self.audioInBuff) >= self.blockSamplesCount:
            block = self.audioInBuff[: self.blockSamplesCount]
            self.audioInBuff = self.audioInBuff[self.blockSamplesCount :]

            out_wav, _, _, _ = self.changeVoice(block)
            result = np.append(result, out_wav)

        return result.astype(np.float32).tobytes()

    def isSequential(self) -> bool:
        return self.inputDevice.isSequential()

    def onReadyRead(self):
        if self.bytesAvailable() != 0:
            self.readyRead.emit()

    def bytesAvailable(self) -> int:
        srcBytesCount = len(self.audioInBuff) + self.inputDevice.bytesAvailable()
        available = srcBytesCount - srcBytesCount % (self.blockSamplesCount * 4)
        return available


def getAudioDeviceById(deviceId: QByteArray, isInput: bool) -> QAudioDevice:
    devices = QMediaDevices.audioInputs() if isInput else QMediaDevices.audioOutputs()

    for dev in devices:
        if dev.id() == deviceId:
            return dev

    raise AudioDeviceDisappearedException


class Audio:
    def __init__(
        self,
        audioInputDeviceId: QByteArray,
        audioOutputDeviceId: QByteArray,
        sampleRate: int,
        blockSamplesCount: int,
        changeVoice,
    ):
        audioInputDevice = getAudioDeviceById(
            audioInputDeviceId, isInput=True
        )  # TODO: exception
        audioInputFormat = audioInputDevice.preferredFormat()
        audioInputFormat.setSampleRate(sampleRate)
        audioInputFormat.setSampleFormat(QAudioFormat.SampleFormat.Float)
        self.audioSource = QAudioSource(
            audioInputDevice,
            audioInputFormat,
        )  # TODO: check opening

        audioOutputDevice = getAudioDeviceById(
            audioOutputDeviceId, isInput=False
        )  # TODO: exception
        self.audioSink = QAudioSink(
            audioOutputDevice,
            audioInputFormat,
        )  # TODO: check opening

        # Start the IO.
        self.voiceChangerFilter = AudioFilter(
            self.audioSource.start(),
            blockSamplesCount,
            changeVoice,
        )  # TODO: check audioSource.error()
        self.voiceChangerFilter.open(
            QIODevice.OpenModeFlag.ReadOnly
        )  # TODO: check opening

        # Do the loopback.
        self.audioSink.start(self.voiceChangerFilter)  # TODO: check audioSink.error()

        # TODO: connect slots to audioSink/audioSource errors to catch device changes.
