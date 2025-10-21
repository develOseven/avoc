import asyncio
import logging
import os
import shutil
import signal
import sys
from traceback import format_exc

import numpy as np
from PySide6.QtCore import (
    QCommandLineOption,
    QCommandLineParser,
    QObject,
    QSettings,
    QStandardPaths,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMenu,
    QSplashScreen,
    QStackedWidget,
    QSystemTrayIcon,
)
from PySide6_GlobalHotkeys import Listener, bindHotkeys
from voiceconversion.common.deviceManager.DeviceManager import DeviceManager
from voiceconversion.downloader.WeightDownloader import (
    CONTENT_VEC_500_ONNX,
    downloadWeight,
)
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
from .customizeui import CustomizeUiWidget
from .exceptions import (
    FailedToSetModelDirException,
    PipelineNotInitializedException,
    VoiceChangerIsNotSelectedException,
)
from .windowarea import WindowAreaWidget

PRETRAIN_DIR_NAME = "pretrain"
MODEL_DIR_NAME = "model_dir"

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)-15s %(levelname)-8s [%(module)s] %(message)s",
    handlers=[stream_handler],
)

logger = logging.getLogger(__name__)

# The IDs to talk with the keybindings configurator about the voice cards.
VOICE_CARD_KEYBIND_ID_PREFIX = "voice_card_"

ENABLE_PASS_THROUGH_KEYBIND_ID = "enable_pass_through"
DISABLE_PASS_THROUGH_KEYBIND_ID = "disable_pass_through"


class MainWindow(QMainWindow):
    def initialize(self, modelDir: str):
        centralWidget = QStackedWidget()
        self.setCentralWidget(centralWidget)

        self.windowAreaWidget = WindowAreaWidget(modelDir)
        centralWidget.addWidget(self.windowAreaWidget)

        self.customizeUiWidget = CustomizeUiWidget()

        preferencesMenu = self.menuBar().addMenu("Preferences")

        custumizeUiAction = QAction("Customize...", self)
        custumizeUiAction.triggered.connect(
            lambda: centralWidget.setCurrentWidget(self.customizeUiWidget)
        )
        self.customizeUiWidget.back.connect(
            lambda: centralWidget.setCurrentWidget(self.windowAreaWidget)
        )
        centralWidget.addWidget(self.customizeUiWidget)

        centralWidget.setCurrentWidget(self.windowAreaWidget)

        preferencesMenu.addAction(custumizeUiAction)

        def onVoiceCardHotkey(shortcutId: str):
            if shortcutId.startswith(VOICE_CARD_KEYBIND_ID_PREFIX):
                rowPlusOne = shortcutId.removeprefix(VOICE_CARD_KEYBIND_ID_PREFIX)
                if rowPlusOne.isdigit():
                    row = int(rowPlusOne) - 1  # 1-based indexing
                    if (
                        # 1 placeholder card
                        row < self.windowAreaWidget.voiceCards.count() - 1
                        and row >= 0
                    ):
                        self.windowAreaWidget.voiceCards.setCurrentRow(row)
            elif shortcutId == ENABLE_PASS_THROUGH_KEYBIND_ID:
                self.windowAreaWidget.passThroughButton.setChecked(True)
            elif shortcutId == DISABLE_PASS_THROUGH_KEYBIND_ID:
                self.windowAreaWidget.passThroughButton.setChecked(False)

        self.hotkeyListener = Listener()
        self.hotkeyListener.hotkeyPressed.connect(onVoiceCardHotkey)

        configureKeybindingsAction = QAction("Configure Keybindings...", self)
        configureKeybindingsAction.triggered.connect(
            lambda: bindHotkeys(
                [
                    (
                        f"{VOICE_CARD_KEYBIND_ID_PREFIX}{row}",
                        {"description": f"Select Voice Card {row}"},
                    )
                    for row in range(
                        1,  # 1-based indexing
                        self.windowAreaWidget.voiceCards.count(),  # 1 placeholder card
                        1,
                    )
                ]
                + [
                    (
                        ENABLE_PASS_THROUGH_KEYBIND_ID,
                        {"description": "Enable Pass Through"},
                    ),
                    (
                        DISABLE_PASS_THROUGH_KEYBIND_ID,
                        {"description": "Disable Pass Through"},
                    ),
                ],
            )
        )

        preferencesMenu.addAction(configureKeybindingsAction)

        self.systemTrayIcon = QSystemTrayIcon(self.windowIcon(), self)
        systemTrayMenu = QMenu()
        activateWindowAction = QAction("Show AVoc", self)
        activateWindowAction.triggered.connect(
            lambda: self.windowHandle().requestActivate()
        )
        quitAction = QAction("Quit AVoc", self)
        quitAction.triggered.connect(lambda: QApplication.quit())
        systemTrayMenu.addActions([activateWindowAction, configureKeybindingsAction])
        systemTrayMenu.addSeparator()
        systemTrayMenu.addAction(quitAction)
        self.systemTrayIcon.setContextMenu(systemTrayMenu)
        self.systemTrayIcon.setToolTip(self.windowTitle())
        self.systemTrayIcon.show()

        self.vcm: VoiceChangerManager | None = (
            None  # TODO: remove the no-model-load CLI arg
        )

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()  # closes the window (quits the app if it's the last window)
        else:
            super().keyPressEvent(event)

    def showTrayMessage(self, title: str, msg: str, icon: QIcon | QPixmap):
        self.systemTrayIcon.showMessage(title, msg, icon, 1000)


class VoiceChangerManager(QObject):

    modelUpdated = Signal(int)
    modelSettingsLoaded = Signal(int, float, float)

    def __init__(self, modelDir: str, pretrainDir: str):
        super().__init__()

        self.modelDir = modelDir
        self.pretrainDir = pretrainDir
        self.audio: Audio | None = None

        voiceChangerSettings = self.getVoiceChangerSettings()
        self.passThrough = False

        self.modelSlotManager = ModelSlotManager.get_instance(
            self.modelDir, "upload_dir"
        )  # TODO: fix the dir

        self.device_manager = DeviceManager.get_instance()
        self.devices = self.device_manager.list_devices()
        self.device_manager.initialize(
            voiceChangerSettings.gpu,
            voiceChangerSettings.forceFp32,
            voiceChangerSettings.disableJit,
        )

        self.vc = VoiceChangerV2(voiceChangerSettings)

    def getVoiceChangerSettings(self):
        voiceChangerSettings = VoiceChangerSettings()
        audioSettings = QSettings()
        audioSettings.beginGroup("AudioSettings")
        interfaceSettings = QSettings()
        interfaceSettings.beginGroup("Interface")
        voiceChangerSettingsDict = {
            "version": "v1",
            "modelSlotIndex": int(interfaceSettings.value("currentVoiceCardIndex", -1)),
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

        self.modelSettingsLoaded.emit(
            slotInfo.defaultTune,
            slotInfo.defaultFormantShift,
            slotInfo.defaultIndexRatio,
        )

        if slotInfo.voiceChangerType == self.vc.get_type():
            self.vc.set_slot_info(
                slotInfo,
                self.pretrainDir,
            )
            # TODO: unify changing properties that don't need reinit.
            self.vc.vcmodel.settings.tran = slotInfo.defaultTune
            self.vc.vcmodel.settings.formantShift = slotInfo.defaultFormantShift
            self.vc.vcmodel.settings.indexRatio = slotInfo.defaultIndexRatio
        elif slotInfo.voiceChangerType == "RVC":
            logger.info("Loading RVC...")
            self.vc.initialize(
                RVCr2(
                    self.modelDir,
                    os.path.join(self.pretrainDir, CONTENT_VEC_500_ONNX),
                    slotInfo,
                    voiceChangerSettings,
                ),
                self.pretrainDir,
            )
        else:
            logger.error(f"Unknown voice changer model: {slotInfo.voiceChangerType}")

    def setModelSettings(
        self,
        pitch: int,
        formantShift: float,
        index: float,
    ):
        voiceChangerSettings = self.getVoiceChangerSettings()
        val = voiceChangerSettings.modelSlotIndex
        slotInfo = self.modelSlotManager.get_slot_info(val)
        if slotInfo is None or slotInfo.voiceChangerType is None:
            logger.warning(f"Model slot is not found {val}")
            return

        slotInfo.defaultTune = pitch
        slotInfo.defaultFormantShift = formantShift
        slotInfo.defaultIndexRatio = index

        if self.vc.vcmodel is not None:
            # TODO: unify changing properties that don't need reinit.
            self.vc.vcmodel.settings.tran = slotInfo.defaultTune
            self.vc.vcmodel.settings.formantShift = slotInfo.defaultFormantShift
            self.vc.vcmodel.settings.indexRatio = slotInfo.defaultIndexRatio

        self.modelSlotManager.save_model_slot(val, slotInfo)

    def setRunning(self, running: bool, passThrough: bool):
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
                self.changeVoice,
            )  # TODO: pass settings
            self.audio.voiceChangerFilter.passThrough = passThrough
        else:
            self.audio = None

    def changeVoice(
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

    def importModel(self, params: LoadModelParams):
        slotDir = os.path.join(
            self.modelDir,
            str(params.slot),
        )

        iconFile = ""
        if os.path.isdir(slotDir):
            # Replacing existing model, delete everything except for the icon.
            slotInfo = self.modelSlotManager.get_slot_info(params.slot)
            iconFile = slotInfo.iconFile
            for entry in os.listdir(slotDir):
                if entry != iconFile:
                    filePath = os.path.join(slotDir, entry)
                    if os.path.isdir(filePath):
                        shutil.rmtree(filePath)
                    else:
                        os.remove(filePath)

        for file in params.files:
            logger.info(f"FILE: {file}")
            srcPath = os.path.join(file.dir, file.name)
            dstDir = os.path.join(
                self.modelDir,
                str(params.slot),
                file.dir,
            )
            dstPath = os.path.join(dstDir, os.path.basename(file.name))
            os.makedirs(dstDir, exist_ok=True)
            logger.info(f"Copying {srcPath} -> {dstPath}")
            shutil.copy(srcPath, dstPath)
            file.name = os.path.basename(dstPath)

        if params.voiceChangerType == "RVC":
            slotInfo = RVCModelSlotGenerator.load_model(params, self.modelDir)
            self.modelSlotManager.save_model_slot(params.slot, slotInfo)

        # Restore icon.
        slotInfo = self.modelSlotManager.get_slot_info(params.slot)
        slotInfo.iconFile = iconFile
        self.modelSlotManager.save_model_slot(params.slot, slotInfo)

        self.modelUpdated.emit(params.slot)

    def setModelIcon(self, slot: int, iconFile: str):
        iconFileBaseName = os.path.basename(iconFile)
        storePath = os.path.join(self.modelDir, str(slot), iconFileBaseName)
        try:
            shutil.copy(iconFile, storePath)
        except shutil.SameFileError:
            pass
        slotInfo = self.modelSlotManager.get_slot_info(slot)
        if slotInfo.iconFile != "" and slotInfo.iconFile != iconFileBaseName:
            os.remove(os.path.join(self.modelDir, str(slot), slotInfo.iconFile))
        slotInfo.iconFile = iconFileBaseName
        self.modelSlotManager.save_model_slot(slot, slotInfo)
        self.modelUpdated.emit(slot)


def main():
    app = QApplication(sys.argv)
    app.setDesktopFileName("AVoc")
    app.setOrganizationName("AVocOrg")
    app.setApplicationName("AVoc")

    iconFilePath = os.path.join(os.path.dirname(__file__), "AVoc.svg")

    icon = QIcon()
    icon.addFile(iconFilePath)

    app.setWindowIcon(icon)

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
    timer.timeout.connect(lambda: None)  # Let the interpreter run each 250 ms.

    window = MainWindow()
    window.setWindowTitle("AVoc")

    splash = QSplashScreen(QPixmap(iconFilePath))
    splash.show()  # Order is important.
    window.show()  # Order is important. And calling window.show() is important.
    window.hide()
    app.processEvents()

    # Set the path where the voice models are stored and pretrained weights are loaded.
    appLocalDataLocation = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    if appLocalDataLocation == "":
        raise FailedToSetModelDirException

    # Check or download models that used internally by the algorithm.
    pretrainDir = os.path.join(appLocalDataLocation, PRETRAIN_DIR_NAME)
    asyncio.run(downloadWeight(pretrainDir))

    # Lay out the window.
    window.initialize(os.path.join(appLocalDataLocation, MODEL_DIR_NAME))

    # Create the voice changer and connect it to the controls.
    window.vcm = VoiceChangerManager(window.windowAreaWidget.modelDir, pretrainDir)
    window.windowAreaWidget.startButton.toggled.connect(
        lambda checked: window.vcm.setRunning(
            checked, window.windowAreaWidget.passThroughButton.isChecked()
        )
    )

    def setPassThrough(passThrough: bool):
        if window.vcm.audio is not None:
            window.vcm.audio.voiceChangerFilter.passThrough = passThrough

    window.windowAreaWidget.passThroughButton.toggled.connect(setPassThrough)

    modelSettingsGroupBox = window.windowAreaWidget.modelSettingsGroupBox

    def onModelSettingsChanged():
        window.vcm.setModelSettings(
            pitch=modelSettingsGroupBox.pitchSpinBox.value(),
            formantShift=modelSettingsGroupBox.formantShiftDoubleSpinBox.value(),
            index=modelSettingsGroupBox.indexDoubleSpinBox.value(),
        )

    modelSettingsGroupBox.changed.connect(onModelSettingsChanged)

    interfaceSettings = QSettings()
    interfaceSettings.beginGroup("Interface")

    def onVoiceCardChanged() -> None:
        modelSettingsGroupBox.changed.disconnect(onModelSettingsChanged)
        window.vcm.initialize()
        modelSettingsGroupBox.changed.connect(onModelSettingsChanged)
        if bool(interfaceSettings.value("showNotifications", True)):
            voiceCardWidget: QLabel = window.windowAreaWidget.voiceCards.itemWidget(
                window.windowAreaWidget.voiceCards.currentItem()
            )
            pixmap = voiceCardWidget.pixmap()
            window.showTrayMessage(
                window.windowTitle(),
                f"Switched to {voiceCardWidget.toolTip()}",
                pixmap,
            )

    def onModelSettingsLoaded(pitch: int, formantShift: float, index: float):
        modelSettingsGroupBox.pitchSpinBox.setValue(pitch)
        modelSettingsGroupBox.formantShiftDoubleSpinBox.setValue(formantShift)
        modelSettingsGroupBox.indexDoubleSpinBox.setValue(index)

    window.vcm.modelSettingsLoaded.connect(onModelSettingsLoaded)

    window.windowAreaWidget.voiceCards.currentRowChanged.connect(onVoiceCardChanged)
    window.windowAreaWidget.voiceCards.droppedModelFiles.connect(
        lambda loadModelParams: window.vcm.importModel(loadModelParams)
    )
    window.windowAreaWidget.voiceCards.droppedIconFile.connect(
        lambda slot, iconFile: window.vcm.setModelIcon(slot, iconFile)
    )
    window.vcm.modelUpdated.connect(
        lambda slot: window.windowAreaWidget.voiceCards.onVoiceCardUpdated(slot),
    )

    audioSettingsGroupBox = window.windowAreaWidget.audioSettingsGroupBox
    audioSettingsGroupBox.sampleRateComboBox.currentIndexChanged.connect(
        lambda: window.vcm.initialize()
    )  # It isn't running when changing sample rate.

    # Load the current voice model if any.
    if not clParser.isSet(noModelLoadOption):
        window.vcm.initialize()

    # Show the window
    window.resize(1980, 1080)  # TODO: store interface dimensions
    window.show()
    splash.finish(window)

    sys.exit(app.exec())
