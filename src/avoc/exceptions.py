class VoiceChangerIsNotSelectedException(Exception):
    def __str__(self):
        return repr("Voice Changer is not selected.")


class PipelineNotInitializedException(Exception):
    def __str__(self):
        return repr("Pipeline is not initialized.")


class AudioDeviceDisappearedException(Exception):
    def __str__(self):
        return repr("Audio device disappeared.")


class FailedToMoveVoiceCardException(Exception):
    def __str__(self):
        return repr("Failed to move voice card.")


class FailedToSetModelDirException(Exception):
    def __str__(self):
        return repr("Failed set the directory for storing the voice models.")
