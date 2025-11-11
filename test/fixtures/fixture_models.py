import pytest
from voiceconversion.imported_model_info_manager import ImportedModelInfoManager

from avoc.main import getModelDir, getVoiceCardsDir
from avoc.voicecardsmanager import VoiceCardsManager

from ..mocks.mock_rvcimportedmodelinfo import newInfo


@pytest.fixture
def savedVoiceCard():
    importedModelInfoManager = ImportedModelInfoManager(getModelDir())
    voiceCardsManager = VoiceCardsManager(importedModelInfoManager, getVoiceCardsDir())
    info0 = newInfo(importedModelInfoManager, name="m0")
    voiceCardsManager.set(0, info0)


@pytest.fixture
def savedTwoVoiceCards():
    importedModelInfoManager = ImportedModelInfoManager(getModelDir())
    voiceCardsManager = VoiceCardsManager(importedModelInfoManager, getVoiceCardsDir())
    info0 = newInfo(importedModelInfoManager, name="m0")
    info1 = newInfo(importedModelInfoManager, name="m1")
    voiceCardsManager.set(0, info0)
    voiceCardsManager.set(1, info1)
