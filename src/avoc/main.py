import asyncio
import logging
import os
import signal
import sys
from contextlib import AbstractContextManager, contextmanager
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
from voiceconversion.common.deviceManager.DeviceManager import (
    DeviceManager,
    with_device_manager_context,
)
from voiceconversion.data.imported_model_info import RVCImportedModelInfo
from voiceconversion.downloader.WeightDownloader import downloadWeight
from voiceconversion.imported_model_info_manager import ImportedModelInfoManager
from voiceconversion.RVC.RVCr2 import RVCr2
from voiceconversion.utils.import_model import import_model
from voiceconversion.utils.import_model_params import ImportModelParams
from voiceconversion.utils.VoiceChangerModel import AudioInOutFloat
from voiceconversion.voice_changer_settings import VoiceChangerSettings
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
    CROSS_FADE_OVERLAP_SIZE,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_EXTRA_CONVERT_SIZE,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SILENT_THRESHOLD,
    loadF0Det,
    loadGpu,
)
from .voicecardsmanager import VoiceCardsManager
from .windowarea import WindowAreaWidget

PRETRAIN_DIR_NAME = "pretrain"
MODEL_DIR_NAME = "model_dir"
VOICE_CARDS_DIR_NAME = "voice_cards_dir"

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
    closed = Signal()

    def initialize(self, voiceCardsManager: VoiceCardsManager):
        centralWidget = QStackedWidget()
        self.loadingOverlay = LoadingOverlay(centralWidget)
        self.loadingOverlay.hide()
        self.setCentralWidget(centralWidget)

        self.windowAreaWidget = WindowAreaWidget(voiceCardsManager)
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

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()  # closes the window (quits the app if it's the last window)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.closed.emit()
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


@with_device_manager_context
def appendVoiceChanger(
    voiceChangerSettings: VoiceChangerSettings,
    pretrainDir: str,
) -> VoiceChangerV2:
    DeviceManager.get_instance().initialize(
        voiceChangerSettings.gpu,
        voiceChangerSettings.forceFp32,
        voiceChangerSettings.disableJit,
    )

    newVcs = VoiceChangerV2(voiceChangerSettings)

    logger.info("Loading RVC...")
    newVcs.initialize(
        RVCr2(
            voiceChangerSettings,
        ),
        pretrainDir,
    )
    return newVcs


class VoiceChangerManager(QObject):

    modelUpdated = Signal(int)
    modelSettingsLoaded = Signal(int, float, float)

    def __init__(
        self,
        voiceCardsManager: VoiceCardsManager,
        pretrainDir: str,
        longOperationCm: AbstractContextManager,
    ):
        super().__init__()

        self.vcs: list[VoiceChangerV2] = []
        self.vcLoaded = False

        self.voiceCardsManager = voiceCardsManager
        self.pretrainDir = pretrainDir
        self.audio: AudioQtMultimedia | AudioPipeWire | None = None

        settings = QSettings()
        settings.beginGroup("InterfaceSettings")

        self.passThrough = bool(settings.value("passThrough", False, type=bool))

        self.longOperationCm = longOperationCm

    def getVoiceChangerSettings(
        self, voiceCardIndex: int
    ) -> VoiceChangerSettings | None:
        importedModelInfo = self.voiceCardsManager.get(voiceCardIndex)
        if importedModelInfo is None:
            logger.warning(f"Voice card is not found {voiceCardIndex}")
            return None

        if importedModelInfo.voiceChangerType != "RVC":
            logger.error(
                f"Unknown voice changer model type: {importedModelInfo.voiceChangerType}"
            )
            return None
        assert type(importedModelInfo) is RVCImportedModelInfo

        processingSettings = QSettings()
        processingSettings.beginGroup("ProcessingSettings")
        sampleRate = processingSettings.value(
            "sampleRate", DEFAULT_SAMPLE_RATE, type=int
        )
        gpuIndex, devices = loadGpu()
        f0DetIndex, f0Detectors = loadF0Det()

        return VoiceChangerSettings(
            inputSampleRate=sampleRate,
            outputSampleRate=sampleRate,
            gpu=devices[gpuIndex]["id"],
            extraConvertSize=processingSettings.value(
                "extraConvertSize", DEFAULT_EXTRA_CONVERT_SIZE, type=float
            ),
            serverReadChunkSize=processingSettings.value(
                "chunkSize", DEFAULT_CHUNK_SIZE, type=int
            ),
            crossFadeOverlapSize=processingSettings.value(
                "crossFadeOverlapSize", CROSS_FADE_OVERLAP_SIZE, type=float
            ),
            # Avoid conversions, assume TF32 is ON internally.
            # TODO: test delay. Maybe FP16 if no TF32 available.
            forceFp32=True,
            disableJit=0,
            dstId=0,
            f0Detector=f0Detectors[f0DetIndex],
            silentThreshold=processingSettings.value(
                "silentThreshold", DEFAULT_SILENT_THRESHOLD, type=int
            ),
            silenceFront=1,
            rvcImportedModelInfo=importedModelInfo,
        )

    def initialize(self):
        interfaceSettings = QSettings()
        interfaceSettings.beginGroup("InterfaceSettings")
        voiceCardIndex = interfaceSettings.value("currentVoiceCardIndex", 0, type=int)
        assert type(voiceCardIndex) is int

        voiceChangerSettings = self.getVoiceChangerSettings(voiceCardIndex)
        if voiceChangerSettings is None:
            self.vcLoaded = False
            return

        try:
            index = next(
                i
                for i, vc in enumerate(self.vcs)
                if vc.settings == voiceChangerSettings
            )
            tmp = self.vcs[index]
            self.vcs[index] = self.vcs[-1]
            self.vcs[-1] = tmp
            foundInCache = True
        except StopIteration:
            foundInCache = False

        if not foundInCache:
            interfaceSettings = QSettings()
            interfaceSettings.beginGroup("InterfaceSettings")
            cachedModelsCount = interfaceSettings.value(
                "cachedModelsCount", DEFAULT_CACHED_MODELS_COUNT, type=int
            )
            assert type(cachedModelsCount) is int
            self.vcs = self.vcs[-cachedModelsCount:]
            with self.longOperationCm():
                newVcs = appendVoiceChanger(voiceChangerSettings, self.pretrainDir)
                self.vcs.append(newVcs)

        importedModelInfo = self.voiceCardsManager.get(voiceCardIndex)
        assert type(importedModelInfo) is RVCImportedModelInfo
        self.modelSettingsLoaded.emit(
            importedModelInfo.defaultTune,
            importedModelInfo.defaultFormantShift,
            importedModelInfo.defaultIndexRatio,
        )

        self.vcLoaded = True

    def setModelSettings(
        self,
        pitch: int,
        formantShift: float,
        index: float,
    ):
        interfaceSettings = QSettings()
        interfaceSettings.beginGroup("InterfaceSettings")
        voiceCardIndex = interfaceSettings.value("currentVoiceCardIndex", 0, type=int)
        assert type(voiceCardIndex) is int
        importedModelInfo = self.voiceCardsManager.get(voiceCardIndex)
        if importedModelInfo is None:
            logger.warning(f"Voice card is not found {voiceCardIndex}")
            return

        importedModelInfo.defaultTune = pitch
        importedModelInfo.defaultFormantShift = formantShift
        importedModelInfo.defaultIndexRatio = index

        if self.vcLoaded:
            assert type(self.vcs[-1].vcmodel) is RVCr2
            self.vcs[-1].vcmodel.settings.rvcImportedModelInfo = importedModelInfo

        self.voiceCardsManager.save(importedModelInfo)

    def onRemoveVoiceCards(self):
        remaining = []
        for vc in self.vcs:
            if (
                self.voiceCardsManager.importedModelInfoManager.get(
                    vc.settings.rvcImportedModelInfo.id
                )
                is None
            ):
                continue
        self.vcs = remaining

    def setRunning(self, running: bool):
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
                audioPipeWireSettings = QSettings()
                audioPipeWireSettings.beginGroup("AudioPipeWireSettings")
                self.audio = AudioPipeWire(
                    bool(audioPipeWireSettings.value("autoLink", True)),
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
        else:
            assert self.audio is not None
            self.audio.exit()
            self.audio = None

    def setPassThrough(self, passThrough: bool):
        self.passThrough = passThrough

    def changeVoice(
        self, receivedData: AudioInOutFloat
    ) -> tuple[AudioInOutFloat, float, list[int], tuple | None]:
        if not self.vcLoaded:
            return (
                np.zeros(1, dtype=np.float32),
                0,
                [0, 0, 0],
                ("VoiceChangerIsNotSelectedException", ""),
            )
            # TODO: check for exception, remove NotSelectedException from lib

        try:
            audio, vol, perf = self.vcs[-1].on_request(receivedData)
            if self.passThrough:
                return receivedData, 1, [0, 0, 0], None
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

    def importModel(self, voiceCardIndex: int, params: ImportModelParams):
        importedModelInfo = import_model(
            self.voiceCardsManager.importedModelInfoManager,
            params,
            self.voiceCardsManager.get(voiceCardIndex),
        )
        if importedModelInfo is not None:
            self.voiceCardsManager.set(voiceCardIndex, importedModelInfo)
            self.modelUpdated.emit(voiceCardIndex)

    def setVoiceCardIcon(self, voiceCardIndex: int, iconFile: str):
        self.voiceCardsManager.setIcon(voiceCardIndex, iconFile)
        self.modelUpdated.emit(voiceCardIndex)


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

    importedModelInfoManager = ImportedModelInfoManager(
        os.path.join(appLocalDataLocation, MODEL_DIR_NAME)
    )

    voiceCardsManager = VoiceCardsManager(
        importedModelInfoManager,
        os.path.join(appLocalDataLocation, VOICE_CARDS_DIR_NAME),
    )

    # Lay out the window.
    window.initialize(voiceCardsManager)

    @contextmanager
    def longOperationCm():
        try:
            window.loadingOverlay.show()
            app.processEvents()
            yield
        finally:
            window.loadingOverlay.hide()

    # Create the voice changer and connect it to the controls.
    vcm = VoiceChangerManager(voiceCardsManager, pretrainDir, longOperationCm)
    window.closed.connect(lambda: vcm.audio.exit() if vcm.audio is not None else None)

    window.windowAreaWidget.startButton.toggled.connect(vcm.setRunning)

    def onAudioRunning(startButtonChecked: bool):
        cuiw = window.customizeUiWidget
        if HAS_PIPEWIRE:
            if startButtonChecked:
                cuiw.audioPipeWireSettingsGroupBox.autoLinkCheckBox.toggled.connect(
                    vcm.audio.setAutoLink
                )
        else:
            cuiw.audioQtMultimediaSettingsGroupBox.setEnabled(not startButtonChecked)

    window.windowAreaWidget.startButton.toggled.connect(
        onAudioRunning, Qt.ConnectionType.UniqueConnection
    )

    def setPassThrough(passThrough: bool):
        oldPassThrough = vcm.passThrough
        if oldPassThrough != passThrough:
            vcm.setPassThrough(passThrough)
            window.showTrayMessage(
                window.windowTitle(),
                f"Pass Through {"On" if passThrough else "Off"}",
            )

    window.windowAreaWidget.passThroughButton.toggled.connect(setPassThrough)

    modelSettingsGroupBox = window.windowAreaWidget.modelSettingsGroupBox

    def onModelSettingsChanged():
        vcm.setModelSettings(
            pitch=modelSettingsGroupBox.pitchSpinBox.value(),
            formantShift=modelSettingsGroupBox.formantShiftDoubleSpinBox.value(),
            index=modelSettingsGroupBox.indexDoubleSpinBox.value(),
        )

    modelSettingsGroupBox.changed.connect(onModelSettingsChanged)

    interfaceSettings = QSettings()
    interfaceSettings.beginGroup("InterfaceSettings")

    def onVoiceCardChanged() -> None:
        modelSettingsGroupBox.changed.disconnect(onModelSettingsChanged)
        vcm.initialize()
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

    vcm.modelSettingsLoaded.connect(onModelSettingsLoaded)

    window.windowAreaWidget.voiceCards.currentRowChanged.connect(onVoiceCardChanged)

    window.windowAreaWidget.cardMoved.connect(voiceCardsManager.moveCard)

    window.windowAreaWidget.cardsRemoved.connect(voiceCardsManager.removeCard)
    window.windowAreaWidget.cardsRemoved.connect(
        lambda first, last: vcm.onRemoveVoiceCards()
    )

    window.windowAreaWidget.voiceCards.droppedModelFiles.connect(vcm.importModel)
    window.windowAreaWidget.voiceCards.droppedIconFile.connect(vcm.setVoiceCardIcon)
    vcm.modelUpdated.connect(window.windowAreaWidget.voiceCards.onVoiceCardUpdated)

    # Load the current voice model if any.
    if not clParser.isSet(noModelLoadOption):
        vcm.initialize()
        if vcm.vcLoaded:
            # Immediately start if it was saved in settings.
            interfaceSettings = QSettings()
            interfaceSettings.beginGroup("InterfaceSettings")
            running = interfaceSettings.value("running", False, type=bool)
            assert type(running) is bool
            window.windowAreaWidget.startButton.setChecked(running)
            onAudioRunning(running)
            window.windowAreaWidget.startButton.toggled.connect(
                lambda checked: interfaceSettings.setValue("running", checked)
            )

    # Show the window
    window.resize(1980, 1080)  # TODO: store interface dimensions
    window.show()
    splash.finish(window)

    sys.exit(app.exec())
