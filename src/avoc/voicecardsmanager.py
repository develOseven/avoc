import json
import logging
import os
import shutil
from pathlib import Path

from voiceconversion.data.imported_model_info import ImportedModelInfo
from voiceconversion.imported_model_info_manager import ImportedModelInfoManager

from .exceptions import FailedToDeleteVoiceCardException, FailedToMoveVoiceCardException

VOICECARDS_FILE = "voicecards.json"
ICONS_DIR = "icons"

logger = logging.getLogger(__name__)


class VoiceCardsManager:
    def __init__(
        self, importedModelInfoManager: ImportedModelInfoManager, voiceCardsDir: str
    ):
        self.importedModelInfoManager = importedModelInfoManager
        self.voiceCards: dict[int, int] = {}

        os.makedirs(voiceCardsDir, exist_ok=True)
        self.voicecardsFile = os.path.join(voiceCardsDir, VOICECARDS_FILE)
        if os.path.exists(self.voicecardsFile):
            with open(self.voicecardsFile, encoding="utf-8") as f:
                voiceCardsDict = json.load(f)
                for voiceCardIndexStr, id in voiceCardsDict.items():
                    if type(voiceCardIndexStr) is str and voiceCardIndexStr.isdigit():
                        if type(id) is int and id >= 0:
                            self.voiceCards[int(voiceCardIndexStr)] = id

        self.iconsDir = Path(voiceCardsDir) / ICONS_DIR
        os.makedirs(self.iconsDir, exist_ok=True)

    def get(self, voiceCardIndex: int) -> ImportedModelInfo | None:
        id = self.voiceCards.get(voiceCardIndex)
        return self.importedModelInfoManager.get(id) if id is not None else None

    def _saveIndices(self):
        with open(self.voicecardsFile, "w") as f:
            json.dump(self.voiceCards, f, indent=4)

    def set(self, voiceCardIndex: int, importedModelInfo: ImportedModelInfo):
        self.voiceCards[voiceCardIndex] = importedModelInfo.id
        self._saveIndices()

    def save(self, importedModelInfo: ImportedModelInfo):
        self.importedModelInfoManager.save(importedModelInfo)

    def getIcon(self, voiceCardIndex: int) -> str | None:
        id = self.voiceCards.get(voiceCardIndex)
        if id is None:
            return None
        for entry in self.iconsDir.iterdir():
            if entry.stem == str(id):
                return str(entry)
        return None

    def setIcon(self, voiceCardIndex: int, iconFile: str):
        id = self.voiceCards.get(voiceCardIndex)
        if id is None:
            logger.warning(f"voice card index is not found {voiceCardIndex}")
            return

        storeName = f"{id}{Path(iconFile).suffix}"
        storePath = self.iconsDir / storeName
        try:
            shutil.copy(iconFile, storePath)
        except shutil.SameFileError:
            pass

        for entry in self.iconsDir.iterdir():
            if entry.name != storeName and entry.stem == str(id):
                entry.unlink()

    def count(self) -> int:
        return len(self.voiceCards)

    def moveCard(self, source: int, destination: int):
        total = self.count()

        if not (0 <= source < total) or not (0 <= destination <= total):
            raise FailedToMoveVoiceCardException("Invalid indices")

        if destination > source:
            destination -= 1

        voiceCards: dict[int, int] = {}

        for voiceCardIndex, id in self.voiceCards.items():
            if source < destination:
                if source < voiceCardIndex <= destination:
                    voiceCards[voiceCardIndex - 1] = id
                    continue
            else:
                if destination <= voiceCardIndex < source:
                    voiceCards[voiceCardIndex + 1] = id
                    continue
            if voiceCardIndex == source:
                voiceCards[destination] = id
                continue
            voiceCards[voiceCardIndex] = id

        self.voiceCards = voiceCards

        self._saveIndices()

    def removeCard(self, first: int, last: int):
        if first > last:
            raise FailedToDeleteVoiceCardException("Invalid indices")

        voiceCards: dict[int, int] = {}

        for voiceCardIndex, id in self.voiceCards.items():
            if first <= voiceCardIndex <= last:
                self.importedModelInfoManager.remove(id)
            else:
                if voiceCardIndex > last:
                    voiceCards[voiceCardIndex - last - first + 1] = id
                else:
                    voiceCards[voiceCardIndex] = id

        for entry in self.iconsDir.iterdir():
            idStr = entry.stem
            if idStr.isdigit() and first <= int(idStr) <= last:
                entry.unlink()

        self.voiceCards = voiceCards

        self._saveIndices()
