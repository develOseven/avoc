import json
import logging
import signal
import sys
from traceback import format_exc

import numpy as np
from PySide6.QtCore import QCommandLineOption, QCommandLineParser, QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QSystemTrayIcon, QWidget
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

from .audio import Audio
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

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.windowAreaWidget = WindowAreaWidget()
        self.setCentralWidget(self.windowAreaWidget)
        self.vcm: VoiceChangerManager | None = (
            None  # TODO: remove the no-model-load CLI arg
        )

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()  # closes the window (quits the app if it's the last window)
        else:
            super().keyPressEvent(event)

    def showTrayMessage(self):
        systemTrayIcon = QSystemTrayIcon(self)
        systemTrayIcon.show()
        systemTrayIcon.showMessage(
            "Title", "msg", QSystemTrayIcon.MessageIcon.Warning, 1000
        )


class VoiceChangerManager:
    def __init__(self) -> None:
        self.audio: Audio | None = None

        voiceChangerSettings = self.getVoiceChangerSettings()
        self.passThrough = False

        self.modelSlotManager = ModelSlotManager.get_instance(
            "model_dir", "upload_dir"
        )  # TODO: fix the dir

        self.device_manager = DeviceManager.get_instance()
        self.devices = self.device_manager.list_devices()
        self.device_manager.initialize(
            voiceChangerSettings.gpu,
            voiceChangerSettings.forceFp32,
            voiceChangerSettings.disableJit,
        )

        self.vc = VoiceChangerV2(voiceChangerSettings, "tmp_dir")  # TODO: fix the dir
        self.initialize()

    def getVoiceChangerSettings(self):
        voiceChangerSettings = VoiceChangerSettings()
        audioSettings = QSettings()
        audioSettings.beginGroup("AudioSettings")
        interfaceSettings = QSettings()
        interfaceSettings.beginGroup("Interface")
        voiceChangerSettingsDict = {
            "version": "v1",
            "modelSlotIndex": int(interfaceSettings.value("currentVoiceCardIndex")),
            "inputSampleRate": int(
                audioSettings.value("sampleRate")
            ),  # TODO: validation
            "outputSampleRate": int(
                audioSettings.value("sampleRate")
            ),  # TODO: validation
            "gpu": 0,
            "extraConvertSize": 0.1,
            "serverReadChunkSize": 22,
            "crossFadeOverlapSize": 0.1,
            "forceFp32": 0,
            "disableJit": 0,
            "enableServerAudio": 1,
            "exclusiveMode": 0,
            "asioInputChannel": -1,
            "asioOutputChannel": -1,
            "dstId": 0,
            "f0Detector": "rmvpe_onnx",
            "tran": 6,
            "formantShift": 0.0,
            "useONNX": 0,
            "silentThreshold": -90,
            "indexRatio": 0.0,
            "protect": 0.5,
            "silenceFront": 1,
        }
        voiceChangerSettings.set_properties(voiceChangerSettingsDict)
        return voiceChangerSettings

    def initialize(self):
        voiceChangerSettings = self.getVoiceChangerSettings()
        val = voiceChangerSettings.modelSlotIndex
        slotInfo = self.modelSlotManager.get_slot_info(val)
        if slotInfo is None or slotInfo.voiceChangerType is None:
            logger.warning(f"Model slot is not found {val}")
            return

        voiceChangerSettings.set_properties(
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
            logger.info("Loading RVC...")
            self.vc.initialize(
                RVCr2(
                    "model_dir",
                    "pretrain/content_vec_500.onnx",
                    slotInfo,
                    voiceChangerSettings,
                )
            )  # TODO: fix the dir
        else:
            logger.error(f"Unknown voice changer model: {slotInfo.voiceChangerType}")

    def setRunning(self, running: bool):
        if (self.audio is not None) == running:
            return

        if running:
            voiceChangerSettings = self.getVoiceChangerSettings()
            settings = QSettings()
            settings.beginGroup("AudioSettings")
            self.audio = Audio(
                settings.value("audioInputDevice"),
                settings.value("audioOutputDevice"),
                settings.value("sampleRate"),  # TODO: validation
                voiceChangerSettings.serverReadChunkSize * 128,
                self.change_voice,
            )  # TODO: pass settings
        else:
            self.audio = None

    def change_voice(
        self, receivedData: AudioInOutFloat
    ) -> tuple[AudioInOutFloat, float, list[int], tuple | None]:
        if self.passThrough:
            vol = float(np.sqrt(np.square(receivedData).mean(dtype=np.float32)))
            return receivedData, vol, [0, 0, 0], None

        try:
            with self.device_manager.lock:
                audio, vol, perf = self.vc.on_request(receivedData)
            return audio, vol, perf, None
        except VoiceChangerIsNotSelectedException as e:
            logger.exception(e)
            return (
                np.zeros(1, dtype=np.float32),
                0,
                [0, 0, 0],
                ("VoiceChangerIsNotSelectedException", format_exc()),
            )
        except PipelineNotInitializedException as e:
            logger.exception(e)
            return (
                np.zeros(1, dtype=np.float32),
                0,
                [0, 0, 0],
                ("PipelineNotInitializedException", format_exc()),
            )
        except Exception as e:
            logger.exception(e)
            return (
                np.zeros(1, dtype=np.float32),
                0,
                [0, 0, 0],
                ("Exception", format_exc()),
            )


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("A-Voc-Org")
    app.setOrganizationDomain("A-Voc-Domain")
    app.setApplicationName("A-Voc")

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
        window.vcm = VoiceChangerManager()
        window.windowAreaWidget.startButton.toggled.connect(
            lambda checked: window.vcm.setRunning(checked)
        )
        window.windowAreaWidget.voiceCards.currentRowChanged.connect(
            lambda: window.vcm.initialize()
        )
        (
            (
                window.windowAreaWidget.audioSettingsGroupBox.sampleRateComboBox
            ).currentIndexChanged.connect(lambda: window.vcm.initialize())
        )  # It isn't running when changing sample rate.

    window.resize(1980, 1080)  # TODO: store interface dimensions
    window.show()

    sys.exit(app.exec())
