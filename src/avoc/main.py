import asyncio
import logging
import os
import shutil
import signal
import sys
from contextlib import AbstractContextManager, contextmanager
from traceback import format_exc
from typing import Tuple

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
from voiceconversion.common.deviceManager.DeviceManager import (
    DeviceManager,
    with_device_manager_context,
)
from voiceconversion.data.ModelSlot import ModelSlots
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

from .audiobackends import HAS_PIPEWIRE

if HAS_PIPEWIRE:
    from .audiopipewire import AudioPipeWire
else:
    from .audioqtmultimedia import AudioQtMultimedia

from .customizeui import DEFAULT_CACHED_MODELS_COUNT, CustomizeUiWidget
from .exceptionhook import qt_exception_hook
from .exceptions import (
    FailedToSetModelDirException,
    PipelineNotInitializedException,
    VoiceChangerIsNotSelectedException,
)
from .loadingoverlay import LoadingOverlay
from .processingsettings import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_EXTRA_CONVERT_SIZE,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SILENT_THRESHOLD,
    loadF0Det,
    loadGpu,
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

assert qt_exception_hook

# The IDs to talk with the keybindings configurator about the voice cards.
VOICE_CARD_KEYBIND_ID_PREFIX = "voice_card_"

ENABLE_PASS_THROUGH_KEYBIND_ID = "enable_pass_through"
DISABLE_PASS_THROUGH_KEYBIND_ID = "disable_pass_through"


class MainWindow(QMainWindow):
    def initialize(self, modelDir: str):
        centralWidget = QStackedWidget()
        self.loadingOverlay = LoadingOverlay(centralWidget)
        self.loadingOverlay.hide()
        self.setCentralWidget(centralWidget)

        self.windowAreaWidget = WindowAreaWidget(modelDir)
        centralWidget.addWidget(self.windowAreaWidget)

        self.customizeUiWidget = CustomizeUiWidget()

        viewMenu = self.menuBar().addMenu("View")
        hideUiAction = QAction("Hide AVoc", self)
        hideUiAction.triggered.connect(self.hide)

        viewMenu.addAction(hideUiAction)

        showMainWindowAction = QAction("Show Main Window", self)
        showMainWindowAction.triggered.connect(
            lambda: centralWidget.setCurrentWidget(self.windowAreaWidget)
        )
        showMainWindowAction.triggered.connect(
            lambda: viewMenu.removeAction(showMainWindowAction)
        )

        preferencesMenu = self.menuBar().addMenu("Preferences")

        custumizeUiAction = QAction("Customize...", self)
        custumizeUiAction.triggered.connect(
            lambda: centralWidget.setCurrentWidget(self.customizeUiWidget)
        )
        custumizeUiAction.triggered.connect(
            lambda: (
                viewMenu.addAction(showMainWindowAction)
                if centralWidget.currentWidget() == self.customizeUiWidget
                and showMainWindowAction not in viewMenu.actions()
                else None
            )
        )
        self.customizeUiWidget.back.connect(showMainWindowAction.trigger)
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
        activateWindowAction.triggered.connect(lambda: self.show())
        activateWindowAction.triggered.connect(
            lambda: self.windowHandle().requestActivate()
        )
        quitAction = QAction("Quit AVoc", self)
        quitAction.triggered.connect(lambda: self.close())
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

    def closeEvent(self, event):
        if self.vcm is not None and self.vcm.audio is not None:
            self.vcm.audio.exit()
        super().closeEvent(event)

    def showTrayMessage(
        self, title: str, msg: str, icon: QIcon | QPixmap | None = None
    ):
        if icon is not None:
            self.systemTrayIcon.showMessage(title, msg, icon, 1000)
        else:
            self.systemTrayIcon.showMessage(
                title, msg, QSystemTrayIcon.MessageIcon.Information, 1000
            )


class VoiceChangerManager(QObject):

    modelUpdated = Signal(int)
    modelSettingsLoaded = Signal(int, float, float)

    def __init__(
        self, modelDir: str, pretrainDir: str, longOperationCm: AbstractContextManager
    ):
        super().__init__()

        self.vcs: list[VoiceChangerV2] = []

        self.modelDir = modelDir
        self.pretrainDir = pretrainDir
        self.audio: AudioQtMultimedia | AudioPipeWire | None = None

        self.modelSlotManager = ModelSlotManager.get_instance(
            self.modelDir, "upload_dir"
        )  # TODO: fix the dir

        self.longOperationCm = longOperationCm

    def getVoiceChangerSettings(self) -> Tuple[VoiceChangerSettings, ModelSlots | None]:
        voiceChangerSettings = VoiceChangerSettings()
        processingSettings = QSettings()
        processingSettings.beginGroup("ProcessingSettings")
        sampleRate = processingSettings.value(
            "sampleRate", DEFAULT_SAMPLE_RATE, type=int
        )
        gpuIndex, devices = loadGpu()
        f0DetIndex, f0Detectors = loadF0Det()
        voiceChangerSettingsDict = {
            "version": "v1",
            "inputSampleRate": sampleRate,
            "outputSampleRate": sampleRate,
            "gpu": devices[gpuIndex]["id"],
            "extraConvertSize": processingSettings.value(
                "extraConvertSize", DEFAULT_EXTRA_CONVERT_SIZE, type=float
            ),
            "serverReadChunkSize": processingSettings.value(
                "chunkSize", DEFAULT_CHUNK_SIZE, type=int
            ),
            "crossFadeOverlapSize": 0.1,
            # Avoid conversions, assume TF32 is ON internally.
            # TODO: test delay. Maybe FP16 if no TF32 available.
            "forceFp32": True,
            "disableJit": 0,
            "enableServerAudio": 1,
            "exclusiveMode": 0,
            "asioInputChannel": -1,
            "asioOutputChannel": -1,
            "dstId": 0,
            "f0Detector": f0Detectors[f0DetIndex],
            "tran": 0,
            "formantShift": 0.0,
            "useONNX": 0,
            "silentThreshold": processingSettings.value(
                "silentThreshold", DEFAULT_SILENT_THRESHOLD, type=int
            ),
            "indexRatio": 0.0,
            "protect": 0.5,
            "silenceFront": 1,
        }

        interfaceSettings = QSettings()
        interfaceSettings.beginGroup("InterfaceSettings")
        modelSlotIndex = interfaceSettings.value("currentVoiceCardIndex", 0, type=int)
        assert type(modelSlotIndex) is int
        slotInfo = self.modelSlotManager.get_slot_info(modelSlotIndex)

        if slotInfo is not None and slotInfo.voiceChangerType is not None:
            voiceChangerSettingsDict["modelSlotIndex"] = modelSlotIndex
            voiceChangerSettingsDict["tran"] = slotInfo.defaultTune
            voiceChangerSettingsDict["formantShift"] = slotInfo.defaultFormantShift
            voiceChangerSettingsDict["indexRatio"] = slotInfo.defaultIndexRatio
            voiceChangerSettingsDict["protect"] = slotInfo.defaultProtect
        else:
            logger.warning(f"Model slot is not found {modelSlotIndex}")

        voiceChangerSettings.set_properties(voiceChangerSettingsDict)

        return voiceChangerSettings, slotInfo

    def initialize(self):
        voiceChangerSettings, slotInfo = self.getVoiceChangerSettings()

        try:
            index = next(
                i
                for i, vc in enumerate(self.vcs)
                if vc.settings == voiceChangerSettings
            )
            tmp = self.vcs[index]
            self.vcs[index] = self.vcs[-1]
            self.vcs[-1] = tmp
        except StopIteration:
            interfaceSettings = QSettings()
            interfaceSettings.beginGroup("InterfaceSettings")
            cachedModelsCount = interfaceSettings.value(
                "cachedModelsCount", DEFAULT_CACHED_MODELS_COUNT, type=int
            )
            assert type(cachedModelsCount) is int
            self.vcs = self.vcs[-cachedModelsCount:]
            with self.longOperationCm():
                self.appendVoiceChanger(voiceChangerSettings, slotInfo)

        if slotInfo is not None and slotInfo.voiceChangerType is not None:
            self.modelSettingsLoaded.emit(
                slotInfo.defaultTune,
                slotInfo.defaultFormantShift,
                slotInfo.defaultIndexRatio,
            )

    @with_device_manager_context
    def appendVoiceChanger(
        self, voiceChangerSettings: VoiceChangerSettings, slotInfo: ModelSlots
    ) -> None:
        DeviceManager.get_instance().initialize(
            voiceChangerSettings.gpu,
            voiceChangerSettings.forceFp32,
            voiceChangerSettings.disableJit,
        )

        self.vcs.append(VoiceChangerV2(voiceChangerSettings))

        if slotInfo is not None and slotInfo.voiceChangerType is not None:
            if slotInfo.voiceChangerType == self.vcs[-1].get_type():
                self.vcs[-1].set_slot_info(
                    slotInfo,
                    self.pretrainDir,
                )
                # TODO: unify changing properties that don't need reinit.
                self.vcs[-1].vcmodel.settings.tran = slotInfo.defaultTune
                self.vcs[-1].vcmodel.settings.formantShift = (
                    slotInfo.defaultFormantShift
                )
                self.vcs[-1].vcmodel.settings.indexRatio = slotInfo.defaultIndexRatio
            elif slotInfo.voiceChangerType == "RVC":
                logger.info("Loading RVC...")
                self.vcs[-1].initialize(
                    RVCr2(
                        self.modelDir,
                        os.path.join(self.pretrainDir, CONTENT_VEC_500_ONNX),
                        slotInfo,
                        voiceChangerSettings,
                    ),
                    self.pretrainDir,
                )
            else:
                logger.error(
                    f"Unknown voice changer model: {slotInfo.voiceChangerType}"
                )

    def setModelSettings(
        self,
        pitch: int,
        formantShift: float,
        index: float,
    ):
        interfaceSettings = QSettings()
        interfaceSettings.beginGroup("InterfaceSettings")
        modelSlotIndex = interfaceSettings.value("currentVoiceCardIndex", 0, type=int)
        assert type(modelSlotIndex) is int
        slotInfo = self.modelSlotManager.get_slot_info(modelSlotIndex)
        if slotInfo is None or slotInfo.voiceChangerType is None:
            logger.warning(f"Model slot is not found {modelSlotIndex}")
            return

        slotInfo.defaultTune = pitch
        slotInfo.defaultFormantShift = formantShift
        slotInfo.defaultIndexRatio = index

        if self.vcs and self.vcs[-1].vcmodel is not None:
            # TODO: unify changing properties that don't need reinit.
            self.vcs[-1].vcmodel.settings.tran = slotInfo.defaultTune
            self.vcs[-1].vcmodel.settings.formantShift = slotInfo.defaultFormantShift
            self.vcs[-1].vcmodel.settings.indexRatio = slotInfo.defaultIndexRatio

        self.modelSlotManager.save_model_slot(modelSlotIndex, slotInfo)

    def renumberSlots(
        self,
        sourceStart: int,
        sourceEnd: int,
        destinationRow: int,
    ):
        if destinationRow > sourceEnd:
            blockSize = sourceEnd - sourceStart + 1
            for vc in self.vcs:
                oldIndex = vc.settings.get_property("modelSlotIndex")

                if sourceStart <= oldIndex <= sourceEnd:
                    newIndex = oldIndex + (destinationRow - sourceEnd - 1)
                elif sourceEnd < oldIndex < destinationRow:
                    newIndex = oldIndex - blockSize
                else:
                    newIndex = oldIndex

                if newIndex != oldIndex:
                    vc.settings.set_property("modelSlotIndex", newIndex)

        elif destinationRow < sourceStart:
            blockSize = sourceEnd - sourceStart + 1
            for vc in self.vcs:
                oldIndex = vc.settings.get_property("modelSlotIndex")

                if sourceStart <= oldIndex <= sourceEnd:
                    newIndex = oldIndex - (sourceStart - destinationRow)
                elif destinationRow <= oldIndex < sourceStart:
                    newIndex = oldIndex + blockSize
                else:
                    newIndex = oldIndex

                if newIndex != oldIndex:
                    vc.settings.set_property("modelSlotIndex", newIndex)

    def removeSlots(self, first: int, last: int):
        count = last - first + 1

        remaining = []
        for vc in self.vcs:
            idx = vc.settings.get_property("modelSlotIndex")
            if first <= idx <= last:
                continue
            remaining.append(vc)
        self.vcs = remaining

        for vc in self.vcs:
            oldIndex = vc.settings.get_property("modelSlotIndex")
            if oldIndex > last:
                new_index = oldIndex - count
                vc.settings.set_property("modelSlotIndex", new_index)

    def setRunning(self, running: bool, passThrough: bool):
        if (self.audio is not None) == running:
            return

        if running:
            self.initialize()
            processingSettings = QSettings()
            processingSettings.beginGroup("ProcessingSettings")
            chunkSize = processingSettings.value(
                "chunkSize", DEFAULT_CHUNK_SIZE, type=int
            )
            assert type(chunkSize) is int
            sampleRate = processingSettings.value(
                "sampleRate", DEFAULT_SAMPLE_RATE, type=int
            )
            assert type(sampleRate) is int
            if HAS_PIPEWIRE:
                self.audio = AudioPipeWire(
                    sampleRate,
                    chunkSize * 128,
                    self.changeVoice,
                )
            else:
                audioQtMultimediaSettings = QSettings()
                audioQtMultimediaSettings.beginGroup("AudioQtMultimediaSettings")
                self.audio = AudioQtMultimedia(
                    audioQtMultimediaSettings.value("audioInputDevice"),
                    audioQtMultimediaSettings.value("audioOutputDevice"),
                    sampleRate,
                    chunkSize * 128,
                    self.changeVoice,
                )
            # self.audio.voiceChangerFilter.passThrough = passThrough
        else:
            assert self.audio is not None
            self.audio.exit()
            self.audio = None

    def changeVoice(
        self, receivedData: AudioInOutFloat
    ) -> tuple[AudioInOutFloat, float, list[int], tuple | None]:
        try:
            audio, vol, perf = self.vcs[-1].on_request(receivedData)
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

    window = MainWindow()
    window.setWindowTitle("AVoc")

    # Let Ctrl+C in terminal close the application.
    signal.signal(signal.SIGINT, lambda *args: window.close())
    timer = QTimer()
    timer.start(250)
    timer.timeout.connect(lambda: None)  # Let the interpreter run each 250 ms.

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

    @contextmanager
    def longOperationCm():
        try:
            window.loadingOverlay.show()
            app.processEvents()
            yield
        finally:
            window.vcm.initialize()
            window.loadingOverlay.hide()

    # Create the voice changer and connect it to the controls.
    window.vcm = VoiceChangerManager(
        window.windowAreaWidget.modelDir, pretrainDir, longOperationCm
    )
    customizeUiWidget = window.customizeUiWidget
    if not HAS_PIPEWIRE:
        window.windowAreaWidget.startButton.toggled.connect(
            lambda checked: customizeUiWidget.audioQtMultimediaSettingsGroupBox.setEnabled(
                not checked
            )
        )
    window.windowAreaWidget.startButton.toggled.connect(
        lambda checked: window.vcm.setRunning(
            checked,
            window.windowAreaWidget.passThroughButton.isChecked(),
        )
    )

    def setPassThrough(passThrough: bool):
        if window.vcm.audio is not None:
            if window.vcm.audio.voiceChangerFilter.passThrough != passThrough:
                window.vcm.audio.voiceChangerFilter.passThrough = passThrough
                window.showTrayMessage(
                    window.windowTitle(),
                    f"Pass Through {"On" if passThrough else "Off"}",
                )

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
    interfaceSettings.beginGroup("InterfaceSettings")

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
    window.windowAreaWidget.cardsMoved.connect(
        window.vcm.modelSlotManager.renumberSlots
    )
    window.windowAreaWidget.cardsMoved.connect(window.vcm.renumberSlots)
    window.windowAreaWidget.cardsRemoved.connect(
        window.vcm.modelSlotManager.removeSlots
    )
    window.windowAreaWidget.cardsRemoved.connect(window.vcm.removeSlots)
    window.windowAreaWidget.voiceCards.droppedModelFiles.connect(
        lambda loadModelParams: window.vcm.importModel(loadModelParams)
    )
    window.windowAreaWidget.voiceCards.droppedIconFile.connect(
        lambda slot, iconFile: window.vcm.setModelIcon(slot, iconFile)
    )
    window.vcm.modelUpdated.connect(
        lambda slot: window.windowAreaWidget.voiceCards.onVoiceCardUpdated(slot),
    )

    # Load the current voice model if any.
    if not clParser.isSet(noModelLoadOption):
        window.vcm.initialize()
        if window.vcm.vcs[-1].vcmodel is not None:
            # Immediately start if it was saved in settings.
            interfaceSettings = QSettings()
            interfaceSettings.beginGroup("InterfaceSettings")
            running = interfaceSettings.value("running", False, type=bool)
            assert type(running) is bool
            window.windowAreaWidget.startButton.setChecked(running)
            window.windowAreaWidget.startButton.toggled.connect(
                lambda checked: interfaceSettings.setValue("running", checked)
            )

    # Show the window
    window.resize(1980, 1080)  # TODO: store interface dimensions
    window.show()
    splash.finish(window)

    sys.exit(app.exec())
