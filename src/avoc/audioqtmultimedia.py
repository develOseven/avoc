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


class AudioQtMultimediaFilter(QIODevice):
    def __init__(
        self, inputDevice: QIODevice, blockSamplesCount: int, changeVoice, parent=None
    ):
        super().__init__(parent)

        self.passThrough = False
        self.inputDevice = inputDevice
        self.inputDevice.readyRead.connect(self.onReadyRead)
        self.changeVoice = changeVoice
        self.audioInBuff = np.empty(0, dtype=np.float32)
        self.blockSamplesCount = blockSamplesCount

    def readData(self, maxlen: int) -> object:
        if maxlen == 0:
            return b""

        self.audioInBuff = np.append(
            self.audioInBuff,
            np.frombuffer(self.inputDevice.read(maxlen), dtype=np.float32),
        )

        # Use the device buffer limit as an opportunity to catch up.
        self.audioInBuff = self.audioInBuff[-maxlen // 4 :]

        result = np.empty(0, dtype=np.float32)

        if self.passThrough:
            result = self.audioInBuff
            self.audioInBuff = np.empty(0, dtype=np.float32)
            return result.tobytes()

        blockCount = len(self.audioInBuff) // self.blockSamplesCount

        for blockIndex in range(0, blockCount):
            bs = blockIndex * self.blockSamplesCount
            be = bs + self.blockSamplesCount
            out_wav, _, _, _ = self.changeVoice(self.audioInBuff[bs:be])
            result = np.append(result, out_wav)

        return result.tobytes()

    def isSequential(self) -> bool:
        return self.inputDevice.isSequential()

    def onReadyRead(self):
        if self.bytesAvailable() != 0:
            self.readyRead.emit()

    def bytesAvailable(self) -> int:
        srcBytesCount = len(self.audioInBuff) * 4 + self.inputDevice.bytesAvailable()
        available = srcBytesCount - srcBytesCount % (self.blockSamplesCount * 4)
        return available


def getAudioDeviceById(deviceId: QByteArray, isInput: bool) -> QAudioDevice:
    devices = QMediaDevices.audioInputs() if isInput else QMediaDevices.audioOutputs()

    for dev in devices:
        if dev.id() == deviceId:
            return dev

    raise AudioDeviceDisappearedException


class AudioQtMultimedia:
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
        self.voiceChangerFilter = AudioQtMultimediaFilter(
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

    def exit(self):
        pass
