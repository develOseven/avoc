from PySide6.QtCore import QByteArray


class MockAudioQtMultimedia:
    def __init__(
        self,
        audioInputDeviceId: QByteArray,
        audioOutputDeviceId: QByteArray,
        sampleRate: int,
        blockSamplesCount: int,
        changeVoice,
    ):
        self.audioInputDeviceId = audioInputDeviceId
        self.audioOutputDeviceId = audioOutputDeviceId
        self.sampleRate = sampleRate
        self.blockSamplesCount = blockSamplesCount
        self.changeVoice = changeVoice

    def exit(self):
        pass
