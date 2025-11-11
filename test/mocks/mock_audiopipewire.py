class MockAudioPipeWire:
    def __init__(
        self,
        autoLink: bool,
        sampleRate: int,
        blockSamplesCount: int,
        changeVoice,
    ):
        self.autoLink = autoLink
        self.sampleRate = sampleRate
        self.blockSamplesCount = blockSamplesCount
        self.changeVoice = changeVoice

    def setAutoLink(self, autoLink: bool):
        self.autoLink = autoLink

    def exit(self):
        pass
