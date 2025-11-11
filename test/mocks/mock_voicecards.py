from PySide6.QtWidgets import QApplication, QListWidgetItem, QMenu

from avoc.windowarea import VoiceCardsContainer


def deleteVoiceCardByItem(voiceCards: VoiceCardsContainer, item: QListWidgetItem):
    voiceCardWidget = voiceCards.itemWidget(item)

    for w in QApplication.topLevelWidgets():
        if isinstance(w, QMenu):
            if w.parent() == voiceCardWidget and w.objectName() == "VoiceCardPopUpMenu":
                actions = w.actions()
                deleteAction = next(a for a in actions if a.objectName() == "Delete")
                deleteAction.trigger()
                break


def deleteVoiceCard(voiceCards: VoiceCardsContainer, voiceCardIndex: int):
    deleteVoiceCardByItem(voiceCards, voiceCards.item(voiceCardIndex))


def deleteCurrentVoiceCard(voiceCards: VoiceCardsContainer):
    deleteVoiceCardByItem(voiceCards, voiceCards.currentItem())
