import asyncio
import logging
import os
import signal
import sys
from contextlib import AbstractContextManager, contextmanager, nullcontext
from traceback import format_exc
from typing import Callable, Tuple

import numpy as np
from PySide6.QtCore import (
    Property,
    QCoreApplication,
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
from .windowarea import VoiceCardPlaceholderWidget, WindowAreaWidget

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

        self.preferencesMenu = self.menuBar().addMenu("Preferences")

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

        self.preferencesMenu.addAction(custumizeUiAction)

        interfaceSettings = QSettings()
        interfaceSettings.beginGroup("InterfaceSettings")

        self.startAction = QAction(
            "Start",
            self,
            checkable=True,
            enabled=False,
        )
        self.startAction.toggled.connect(
            lambda checked: interfaceSettings.setValue("running", checked)
        )
        # If model loads and triggers the enable, then
        # immediately start if it was saved in settings.
        self.startAction.enabledChanged.connect(
            lambda enabled: (
                self.startAction.setChecked(
                    bool(interfaceSettings.value("running", False, type=bool))
                )
                if enabled
                else None
            )
        )
        self.windowAreaWidget.startButton.setDefaultAction(self.startAction)

        if not HAS_PIPEWIRE:
            cuiw = self.customizeUiWidget
            self.startAction.toggled.connect(
                lambda checked: cuiw.audioQtMultimediaSettingsGroupBox.setEnabled(
                    not checked
                )
            )

        self.passThroughAction = QAction(
            "Pass Through",
            self,
            checkable=True,
            checked=bool(interfaceSettings.value("passThrough", False, type=bool)),
        )
        self.passThroughAction.toggled.connect(
            lambda checked: interfaceSettings.setValue("passThrough", checked)
        )
        self.passThroughAction.toggled.connect(
            lambda checked: self.showTrayMessage(
                self.windowTitle(),
                f"Pass Through {"On" if checked else "Off"}",
            )
        )
        self.windowAreaWidget.passThroughButton.setDefaultAction(self.passThroughAction)

        audioPipeWireSettings = QSettings()
        audioPipeWireSettings.beginGroup("AudioPipeWireSettings")

        self.autoLinkAction = QAction(
            "Auto Link Applications",
            self,
            checkable=True,
            checked=bool(audioPipeWireSettings.value("autoLink", True, type=bool)),
        )
        self.autoLinkAction.toggled.connect(
            lambda checked: audioPipeWireSettings.setValue("autoLink", checked)
        )
        cuiw = self.customizeUiWidget
        cuiw.audioPipeWireSettingsGroupBox.autoLinkCheckBox.setDefaultAction(
            self.autoLinkAction
        )

        self.systemTrayIcon = QSystemTrayIcon(self.windowIcon(), self)
        self.systemTrayMenu = QMenu()
        activateWindowAction = QAction("Show AVoc", self)
        activateWindowAction.triggered.connect(lambda: self.show())
        activateWindowAction.triggered.connect(
            lambda: self.windowHandle().requestActivate()
        )
        quitAction = QAction("Quit AVoc", self)
        quitAction.triggered.connect(lambda: self.close())
        self.systemTrayMenu.addAction(activateWindowAction)
        self.traySeparator = self.systemTrayMenu.addSeparator()
        self.systemTrayMenu.addAction(quitAction)
        self.systemTrayIcon.setContextMenu(self.systemTrayMenu)
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
    vcLoadedChanged = Signal(bool)

    def __init__(
        self,
        voiceCardsManager: VoiceCardsManager,
        pretrainDir: str,
    ):
        super().__init__()

        self.vcs: list[VoiceChangerV2] = []
        self._vcLoaded = False

        self.voiceCardsManager = voiceCardsManager
        self.pretrainDir = pretrainDir
        self.audio: AudioQtMultimedia | AudioPipeWire | None = None

        self.passThrough = False

        self.longOperationCm: Callable[[], AbstractContextManager[None]] = nullcontext

    def setLongOperationCm(
        self, longOperationCm: Callable[[], AbstractContextManager[None]]
    ):
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

        assert type(importedModelInfo) == RVCImportedModelInfo
        importedModelInfo.defaultTune = pitch
        importedModelInfo.defaultFormantShift = formantShift
        importedModelInfo.defaultIndexRatio = index

        if self.vcLoaded:
            assert type(self.vcs[-1].vcmodel) is RVCr2
            self.vcs[-1].vcmodel.settings.rvcImportedModelInfo = importedModelInfo

        self.voiceCardsManager.save(importedModelInfo)

    def onRemoveVoiceCards(self):
        importedModelInfoManager = self.voiceCardsManager.importedModelInfoManager
        remaining = []
        for vc in self.vcs:
            id = vc.settings.rvcImportedModelInfo.id
            if importedModelInfoManager.get(id) is not None:
                remaining.append(vc)
        self.vcs = remaining

    def setPassThrough(self, value: bool):
        self.passThrough = value

    def changeVoice(
        self, receivedData: AudioInOutFloat
    ) -> tuple[AudioInOutFloat, float, list[int], tuple | None]:
        if not self.vcLoaded:
            return (
                np.zeros(len(receivedData), dtype=np.float32),
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

            interfaceSettings = QSettings()
            interfaceSettings.beginGroup("InterfaceSettings")
            currentVoiceCardIndex = interfaceSettings.value(
                "currentVoiceCardIndex", 0, type=int
            )
            assert type(currentVoiceCardIndex) is int
            if voiceCardIndex == currentVoiceCardIndex:
                self.initialize()

            self.modelUpdated.emit(voiceCardIndex)

    def setVoiceCardIcon(self, voiceCardIndex: int, iconFile: str):
        self.voiceCardsManager.setIcon(voiceCardIndex, iconFile)
        self.modelUpdated.emit(voiceCardIndex)

    def readVcLoaded(self) -> bool:
        return self._vcLoaded

    def setVcLoaded(self, value: bool):
        if self._vcLoaded != value:
            self._vcLoaded = value
            self.vcLoadedChanged.emit(self._vcLoaded)

    vcLoaded = Property(bool, readVcLoaded, setVcLoaded, notify=vcLoadedChanged)


def getAppLocalDataLocation() -> str:
    """Get the path where the voice models are stored and pretrained weights are loaded."""
    appLocalDataLocation = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    if appLocalDataLocation == "":
        raise FailedToSetModelDirException
    return appLocalDataLocation


def getPretrainDir() -> str:
    return os.path.join(getAppLocalDataLocation(), PRETRAIN_DIR_NAME)


def getModelDir() -> str:
    return os.path.join(getAppLocalDataLocation(), MODEL_DIR_NAME)


def getVoiceCardsDir() -> str:
    return os.path.join(getAppLocalDataLocation(), VOICE_CARDS_DIR_NAME)


def downloadPretrain():
    """Check or download models that used internally by the algorithm."""
    asyncio.run(downloadWeight(getPretrainDir()))


class AudioHolder:
    def __init__(self) -> None:
        self.audio: AudioPipeWire | AudioQtMultimedia | None = None


def create() -> Tuple[VoiceCardsManager, VoiceChangerManager, AudioHolder]:

    importedModelInfoManager = ImportedModelInfoManager(getModelDir())

    voiceCardsManager = VoiceCardsManager(
        importedModelInfoManager,
        getVoiceCardsDir(),
    )

    vcm = VoiceChangerManager(voiceCardsManager, getPretrainDir())

    return voiceCardsManager, vcm, AudioHolder()


def initialize(
    window: MainWindow,
    voiceCardsManager: VoiceCardsManager,
    vcm: VoiceChangerManager,
    audioHolder: AudioHolder,
) -> None:
    window.initialize(voiceCardsManager)

    @contextmanager
    def longOperationCm():
        try:
            window.loadingOverlay.show()
            QCoreApplication.processEvents()
            yield
        finally:
            window.loadingOverlay.hide()

    vcm.setLongOperationCm(longOperationCm)

    vcm.setPassThrough(window.passThroughAction.isChecked())
    window.passThroughAction.toggled.connect(vcm.setPassThrough)

    vcm.vcLoadedChanged.connect(window.startAction.setEnabled)

    window.startAction.toggled.connect(
        lambda checked: vcm.initialize() if checked else None
    )

    def onStart(checked: bool):
        nonlocal audioHolder
        running = audioHolder.audio is not None
        if running == checked:
            return

        if not checked:
            assert audioHolder.audio is not None
            audioHolder.audio.exit()
            audioHolder.audio = None
            return

        assert audioHolder.audio is None

        processingSettings = QSettings()
        processingSettings.beginGroup("ProcessingSettings")
        chunkSize = processingSettings.value("chunkSize", DEFAULT_CHUNK_SIZE, type=int)
        assert type(chunkSize) is int
        sampleRate = processingSettings.value(
            "sampleRate", DEFAULT_SAMPLE_RATE, type=int
        )
        assert type(sampleRate) is int
        if HAS_PIPEWIRE:
            audioPipeWireSettings = QSettings()
            audioPipeWireSettings.beginGroup("AudioPipeWireSettings")
            audioHolder.audio = AudioPipeWire(
                window.autoLinkAction.isChecked(),
                sampleRate,
                chunkSize * 128,
                vcm.changeVoice,
            )
            window.autoLinkAction.toggled.connect(audioHolder.audio.setAutoLink)
        else:
            audioQtMultimediaSettings = QSettings()
            audioQtMultimediaSettings.beginGroup("AudioQtMultimediaSettings")
            audioHolder.audio = AudioQtMultimedia(
                audioQtMultimediaSettings.value("audioInputDevice"),
                audioQtMultimediaSettings.value("audioOutputDevice"),
                sampleRate,
                chunkSize * 128,
                vcm.changeVoice,
            )

    window.startAction.toggled.connect(onStart)

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
            voiceCardWidget = window.windowAreaWidget.voiceCards.itemWidget(
                window.windowAreaWidget.voiceCards.currentItem()
            )
            assert (
                type(voiceCardWidget) is QLabel
                or type(voiceCardWidget) is VoiceCardPlaceholderWidget
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
    window.windowAreaWidget.cardsRemoved.connect(vcm.onRemoveVoiceCards)

    window.windowAreaWidget.voiceCards.droppedModelFiles.connect(vcm.importModel)
    window.windowAreaWidget.voiceCards.droppedIconFile.connect(vcm.setVoiceCardIcon)
    vcm.modelUpdated.connect(window.windowAreaWidget.voiceCards.onVoiceCardUpdated)

    vcm.initialize()

    # Show the window
    window.resize(1980, 1080)  # TODO: store interface dimensions
    window.show()


def setUpHotkeys(window: MainWindow):
    def onVoiceCardHotkey(shortcutId: str):
        if shortcutId.startswith(VOICE_CARD_KEYBIND_ID_PREFIX):
            rowPlusOne = shortcutId.removeprefix(VOICE_CARD_KEYBIND_ID_PREFIX)
            if rowPlusOne.isdigit():
                row = int(rowPlusOne) - 1  # 1-based indexing
                if (
                    # 1 placeholder card
                    row < window.windowAreaWidget.voiceCards.count() - 1
                    and row >= 0
                ):
                    window.windowAreaWidget.voiceCards.setCurrentRow(row)
        elif shortcutId == ENABLE_PASS_THROUGH_KEYBIND_ID:
            window.passThroughAction.setChecked(True)
        elif shortcutId == DISABLE_PASS_THROUGH_KEYBIND_ID:
            window.passThroughAction.setChecked(False)

    hotkeyListener = Listener(window)
    hotkeyListener.hotkeyPressed.connect(onVoiceCardHotkey)

    configureKeybindingsAction = QAction("Configure Keybindings...", window)
    configureKeybindingsAction.triggered.connect(
        lambda: bindHotkeys(
            [
                (
                    f"{VOICE_CARD_KEYBIND_ID_PREFIX}{row}",
                    {"description": f"Select Voice Card {row}"},
                )
                for row in range(
                    1,  # 1-based indexing
                    window.windowAreaWidget.voiceCards.count(),  # 1 placeholder card
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

    window.preferencesMenu.addAction(configureKeybindingsAction)
    window.systemTrayMenu.insertAction(window.traySeparator, configureKeybindingsAction)


def deinitialize(audioHolder: AudioHolder):
    if audioHolder.audio is not None:
        audioHolder.audio.exit()


def main() -> None:
    app = QApplication(sys.argv)
    app.setDesktopFileName("AVoc")
    app.setOrganizationName("AVocOrg")
    app.setApplicationName("AVoc")

    iconFilePath = os.path.join(os.path.dirname(__file__), "AVoc.svg")
    icon = QIcon()
    icon.addFile(iconFilePath)
    app.setWindowIcon(icon)

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

    downloadPretrain()

    voiceCardsManager, vcm, audioHolder = create()
    initialize(window, voiceCardsManager, vcm, audioHolder)
    setUpHotkeys(window)

    splash.finish(window)

    exitStatus = app.exec()

    deinitialize(audioHolder)

    sys.exit(exitStatus)
