import json
import logging
import os
import shutil
import signal
import sys
from traceback import format_exc

import numpy as np
from PySide6.QtCore import (
    QByteArray,
    QCommandLineOption,
    QCommandLineParser,
    QIODevice,
    QObject,
    Qt,
    QTimer,
    qCritical,
    qInfo,
    qWarning,
)
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QAudioSource, QMediaDevices
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)
from voiceconversion.common.deviceManager.DeviceManager import DeviceManager
from voiceconversion.ModelSlotManager import ModelSlotManager
from voiceconversion.RVC.RVCModelSlotGenerator import (
    RVCModelSlotGenerator,  # Parameters cannot be obtained when imported at startup.
)
from voiceconversion.RVC.RVCr2 import RVCr2
from voiceconversion.utils.LoadModelParams import LoadModelParams
from voiceconversion.utils.VoiceChangerModel import AudioInOutFloat
from voiceconversion.VoiceChangerSettings import VoiceChangerSettings
from voiceconversion.VoiceChangerV2 import VoiceChangerV2

from .exceptions import (
    PipelineNotInitializedException,
    VoiceChangerIsNotSelectedException,
)
from .windowarea import WindowAreaWidget

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)-15s %(levelname)-8s [%(module)s] %(message)s",
    handlers=[stream_handler],
)


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setCentralWidget(WindowAreaWidget())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()  # closes the window (and quits the app if it's the last window)
        else:
            super().keyPressEvent(event)

    def showTrayMessage(self):
        systemTrayIcon = QSystemTrayIcon(self)
        systemTrayIcon.show()
        systemTrayIcon.showMessage(
            "Title", "msg", QSystemTrayIcon.MessageIcon.Warning, 1000
        )


class AudioFilter(QIODevice):
    def __init__(
        self, inputDevice: QIODevice, blockSamplesCount: int, change_voice, parent=None
    ):
        super().__init__(parent)

        self.inputDevice = inputDevice
        self.inputDevice.readyRead.connect(self.onReadyRead)
        self.change_voice = change_voice
        self.audioInBuff = b""
        self.blockSamplesCount = blockSamplesCount

    def isSequential(self) -> bool:
        return self.inputDevice.isSequential()

    def onReadyRead(self):
        if self.bytesAvailable() != 0:
            self.readyRead.emit()

    def bytesAvailable(self) -> int:
        srcBytesCount = len(self.audioInBuff) + self.inputDevice.bytesAvailable()
        return srcBytesCount - srcBytesCount % (self.blockSamplesCount * 4)

    def readData(self, maxlen: int) -> object:
        data: QByteArray = self.inputDevice.read(maxlen)

        output_blocks = []

        self.audioInBuff += bytes(data)

        while len(self.audioInBuff) >= self.blockSamplesCount * 4:
            block = self.audioInBuff[: self.blockSamplesCount * 4]
            self.audioInBuff = self.audioInBuff[
                self.blockSamplesCount * 4 :
            ]  # keep the rest

            out_wav, _, _, _ = self.change_voice(
                np.frombuffer(block, dtype="<f4").copy()
            )
            output_blocks.append(out_wav)

        result = b"".join(output_blocks)

        return result


class Audio(QObject):
    def __init__(self, blockSamplesCount: int, change_voice, parent=None):
        super().__init__(parent)

        # Get the default input device.
        audioInputDevices = QMediaDevices.audioInputs()
        defaultAudioInputDevices = [d for d in audioInputDevices if d.isDefault()]
        audioInputDevice = defaultAudioInputDevices[0]  # TODO: exception
        audioInputFormat = audioInputDevice.preferredFormat()
        audioInputFormat.setSampleRate(48000)
        audioInputFormat.setSampleFormat(QAudioFormat.SampleFormat.Float)
        self.audioSource = QAudioSource(
            audioInputDevice, audioInputFormat
        )  # TODO: check opening

        # Get the default output device.
        audioOutputDevices = QMediaDevices.audioOutputs()
        defaultAudioOutputDevices = [d for d in audioOutputDevices if d.isDefault()]
        audioOutputDevice = defaultAudioOutputDevices[0]  # TODO: exception
        self.audioSink = QAudioSink(
            audioOutputDevice, audioInputFormat
        )  # TODO: check opening

        qInfo(f"format {audioInputFormat}")

        # Start the IO.
        self.voiceChangerFilter = AudioFilter(
            self.audioSource.start(), blockSamplesCount, change_voice
        )  # TODO: check audioSource.error()
        self.voiceChangerFilter.open(
            QIODevice.OpenModeFlag.ReadOnly
        )  # TODO: check opening

        # Do the loopback.
        self.audioSink.start(self.voiceChangerFilter)  # TODO: check audioSink.error()

        # TODO: connect slots to the self.audioSink and self.audioSource errors to catch device changes.


class VoiceChangerManager(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.modelSlotManager = ModelSlotManager.get_instance(
            "model_dir", "upload_dir"
        )  # TODO: fix the dir
        self.settings = VoiceChangerSettings()
        try:
            with open(
                "stored_setting.json", "r", encoding="utf-8"
            ) as f:  # TODO: fix the settings file
                settings = json.load(f)
            self.settings.set_properties(settings)
        except:
            pass

        self.device_manager = DeviceManager.get_instance()
        self.devices = self.device_manager.list_devices()
        self.device_manager.initialize(
            self.settings.gpu, self.settings.forceFp32, self.settings.disableJit
        )

        self.vc = VoiceChangerV2(self.settings, "tmp_dir")  # TODO: fix the dir
        self.initialize(self.settings.modelSlotIndex)

        self.audio = Audio(
            self.settings.serverReadChunkSize * 128, self.change_voice
        )  # TODO: pass settings

    def store_setting(self):
        with open("stored_setting.json", "w") as f:  # TODO: fix the settings file
            json.dump(self.settings.to_dict_stateless(), f)

    def initialize(self, val: int):
        slotInfo = self.modelSlotManager.get_slot_info(val)
        if slotInfo is None or slotInfo.voiceChangerType is None:
            qWarning(f"Model slot is not found {val}")
            return

        self.settings.set_properties(
            {
                "tran": slotInfo.defaultTune,
                "formantShift": slotInfo.defaultFormantShift,
                "indexRatio": slotInfo.defaultIndexRatio,
                "protect": slotInfo.defaultProtect,
            }
        )

        if slotInfo.voiceChangerType == self.vc.get_type():
            self.vc.set_slot_info(slotInfo)
        elif slotInfo.voiceChangerType == "RVC":
            qInfo("Loading RVC...")
            self.vc.initialize(
                RVCr2(
                    "model_dir",
                    "pretrain/content_vec_500.onnx",
                    slotInfo,
                    self.settings,
                )
            )  # TODO: fix the dir
        else:
            qCritical(f"Unknown voice changer model: {slotInfo.voiceChangerType}")

    def change_voice(
        self, receivedData: AudioInOutFloat
    ) -> tuple[AudioInOutFloat, float, list[int], tuple | None]:
        if self.settings.passThrough:
            vol = float(np.sqrt(np.square(receivedData).mean(dtype=np.float32)))
            return receivedData, vol, [0, 0, 0], None

        try:
            with self.device_manager.lock:
                audio, vol, perf = self.vc.on_request(receivedData)
            return audio, vol, perf, None
        except VoiceChangerIsNotSelectedException as e:
            qCritical(e)
            return (
                np.zeros(1, dtype=np.float32),
                0,
                [0, 0, 0],
                ("VoiceChangerIsNotSelectedException", format_exc()),
            )
        except PipelineNotInitializedException as e:
            qCritical(e)
            return (
                np.zeros(1, dtype=np.float32),
                0,
                [0, 0, 0],
                ("PipelineNotInitializedException", format_exc()),
            )
        except Exception as e:
            qCritical(e)
            return (
                np.zeros(1, dtype=np.float32),
                0,
                [0, 0, 0],
                ("Exception", format_exc()),
            )


def main():
    app = QApplication(sys.argv)

    clParser = QCommandLineParser()
    clParser.addHelpOption()
    clParser.addVersionOption()

    noModelLoadOption = QCommandLineOption(
        ["no-model-load"], "Don't load a voice model."
    )
    clParser.addOption(noModelLoadOption)

    clParser.process(app)

    # Let Ctrl+C in terminal close the application.
    signal.signal(signal.SIGINT, lambda *args: QApplication.quit())
    timer = QTimer()
    timer.start(250)
    timer.timeout.connect(lambda: None)  # Let the interpreter run each 500 ms.

    window = MainWindow()
    window.setWindowTitle("A-Voc")

    if not clParser.isSet(noModelLoadOption):
        VoiceChangerManager(window)

    window.resize(1980, 1080)
    window.show()

    sys.exit(app.exec())
