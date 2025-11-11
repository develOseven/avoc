import os
from pathlib import Path

import pytest
from voiceconversion.imported_model_info_manager import ImportedModelInfoManager

from avoc.exceptions import (
    FailedToDeleteVoiceCardException,
    FailedToMoveVoiceCardException,
)
from avoc.voicecardsmanager import VoiceCardsManager

from .mocks.mock_rvcimportedmodelinfo import newInfo


def createTestIconFile(tmp_path, name="icon.png", content=b"ICON"):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


@pytest.fixture
def modelDir(tmp_path):
    d = tmp_path / "model_dir"
    d.mkdir()
    return str(d)


@pytest.fixture
def voiceCardsDir(tmp_path):
    d = tmp_path / "voice_cards_dir"
    d.mkdir()
    return str(d)


def testSetGetAndPersistence(modelDir, voiceCardsDir):
    importedModelInfoManager = ImportedModelInfoManager(modelDir)
    voiceCardsManager = VoiceCardsManager(importedModelInfoManager, voiceCardsDir)

    info0 = newInfo(importedModelInfoManager, name="m0")
    info1 = newInfo(importedModelInfoManager, name="m1")

    voiceCardsManager.set(0, info0)
    voiceCardsManager.set(1, info1)

    g0 = voiceCardsManager.get(0)
    g1 = voiceCardsManager.get(1)
    assert g0.id == info0.id
    assert g1.id == info1.id

    assert voiceCardsManager.count() == 2

    # make a new manager reading the same voicecards dir to check persistence
    voiceCardsManager = VoiceCardsManager(importedModelInfoManager, voiceCardsDir)
    assert voiceCardsManager.get(0).id == info0.id
    assert voiceCardsManager.get(1).id == info1.id


def testSetAndGetIcon(modelDir, voiceCardsDir, tmp_path):
    importedModelInfoManager = ImportedModelInfoManager(modelDir)
    voiceCardsManager = VoiceCardsManager(importedModelInfoManager, voiceCardsDir)

    info = newInfo(importedModelInfoManager, name="withicon")
    voiceCardsManager.set(0, info)

    # create an external icon file and set it
    srcIcon = createTestIconFile(tmp_path, "sample.png", b"PNGDATA")
    voiceCardsManager.setIcon(0, srcIcon)

    iconPath = voiceCardsManager.getIcon(0)
    assert iconPath is not None
    assert os.path.exists(iconPath)
    assert Path(iconPath).stem == str(info.id)
    assert Path(iconPath).suffix == ".png"


def testSetIconReplacesPreviousIcon(modelDir, voiceCardsDir, tmp_path):
    importedModelInfoManager = ImportedModelInfoManager(modelDir)
    voiceCardsManager = VoiceCardsManager(importedModelInfoManager, voiceCardsDir)

    info = newInfo(importedModelInfoManager, name="replaceicon")
    voiceCardsManager.set(0, info)

    # two icons with different suffixes
    icon1 = createTestIconFile(tmp_path, "i1.png", b"ONE")
    icon2 = createTestIconFile(tmp_path, "i2.jpg", b"TWO")

    voiceCardsManager.setIcon(0, icon1)
    first = voiceCardsManager.getIcon(0)
    assert first is not None

    # set a second icon for same id, previous icon file with same stem should be removed
    voiceCardsManager.setIcon(0, icon2)
    new = voiceCardsManager.getIcon(0)
    assert new is not None
    assert Path(new).suffix == ".jpg"

    # ensure only single icon file remains for that id in iconsDir
    icons = list((Path(voiceCardsDir) / "icons").iterdir())
    stems = [p.stem for p in icons]
    assert stems.count(str(info.id)) == 1


def testMoveCardForwardAndBackward(modelDir, voiceCardsDir):
    importedModelInfoManager = ImportedModelInfoManager(modelDir)
    voiceCardsManager = VoiceCardsManager(importedModelInfoManager, voiceCardsDir)

    # create 4 cards
    infos = [newInfo(importedModelInfoManager, name=f"m{i}") for i in range(4)]
    for i, info in enumerate(infos):
        voiceCardsManager.set(i, info)

    # initial order ids by index
    before = [voiceCardsManager.get(i).id for i in range(4)]
    assert before == [0, 1, 2, 3]

    # move index 1 -> destination index 3 (i.e. after index 2)
    voiceCardsManager.moveCard(1, 3)
    after = [voiceCardsManager.get(i).id for i in range(4)]
    # expected: items: index 0 stays, index1 moved to position 2 (destination adjusted),
    assert after == [0, 2, 1, 3]
    # ensure all ids still present
    assert set(after) == set(before)

    # move last to first
    voiceCardsManager.moveCard(3, 0)
    after2 = [voiceCardsManager.get(i).id for i in range(4)]
    assert after2 == [3, 0, 2, 1]
    assert set(after2) == set(before)


def testMoveCardInvalidIndicesRaises(modelDir, voiceCardsDir):
    importedModelInfoManager = ImportedModelInfoManager(modelDir)
    voiceCardsManager = VoiceCardsManager(importedModelInfoManager, voiceCardsDir)

    # create 2 cards
    info0 = newInfo(importedModelInfoManager, name="a")
    info1 = newInfo(importedModelInfoManager, name="b")
    voiceCardsManager.set(0, info0)
    voiceCardsManager.set(1, info1)

    # invalid source
    with pytest.raises(FailedToMoveVoiceCardException):
        voiceCardsManager.moveCard(-1, 1)

    # invalid destination (greater than total)
    with pytest.raises(FailedToMoveVoiceCardException):
        voiceCardsManager.moveCard(0, 3)


def testRemoveCardRangeAndIconsRemoved(modelDir, voiceCardsDir, tmp_path):
    importedModelInfoManager = ImportedModelInfoManager(modelDir)
    voiceCardsManager = VoiceCardsManager(importedModelInfoManager, voiceCardsDir)

    # create 5 cards
    infos = [newInfo(importedModelInfoManager, name=f"rm{i}") for i in range(5)]
    for i, info in enumerate(infos):
        voiceCardsManager.set(i, info)
        # create icons for each and set them
        src = createTestIconFile(
            tmp_path, f"ic_{info.id}.png", bytes(str(info.id), "utf8")
        )
        voiceCardsManager.setIcon(i, src)

    assert voiceCardsManager.count() == 5

    # remove middle range 1..3 (inclusive) => will remove ids of indexes 1,2,3
    ids_to_remove = [voiceCardsManager.get(i).id for i in range(1, 4)]
    voiceCardsManager.removeCard(1, 3)

    # count should be 2 (indexes 0 and remaining last)
    assert voiceCardsManager.count() == 2

    # ensure removed ids no longer present and their storage dirs are deleted
    for removed_id in ids_to_remove:
        # ImportedModelInfoManager.infos should not have these ids
        assert importedModelInfoManager.get(removed_id) is None
        # storageDir should not exist on disk
        # location for storage dir used by ImportedModelInfoManager is model_dir/<id>
        assert not os.path.exists(os.path.join(modelDir, str(removed_id)))

    # icons for removed ids should be removed from iconsDir
    icons_dir = Path(voiceCardsDir) / "icons"
    existing_stems = [p.stem for p in icons_dir.iterdir()]
    for rid in ids_to_remove:
        assert str(rid) not in existing_stems


def testRemoveCardInvalidRangeRaises(modelDir, voiceCardsDir):
    importedModelInfoManager = ImportedModelInfoManager(modelDir)
    voiceCardsManager = VoiceCardsManager(importedModelInfoManager, voiceCardsDir)

    i0 = newInfo(importedModelInfoManager, name="x0")
    voiceCardsManager.set(0, i0)

    with pytest.raises(FailedToDeleteVoiceCardException):
        voiceCardsManager.removeCard(2, 1)


def testSeticonSamefileErrorIsHandled(modelDir, voiceCardsDir):
    importedModelInfoManager = ImportedModelInfoManager(modelDir)
    voiceCardsManager = VoiceCardsManager(importedModelInfoManager, voiceCardsDir)

    info = newInfo(importedModelInfoManager, name="samefile")
    voiceCardsManager.set(0, info)

    # use the same icon file from the icons dir
    icons_dir = Path(voiceCardsDir) / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    expected_name = f"{info.id}.png"
    dest = icons_dir / expected_name
    dest.write_bytes(b"DEST")
    voiceCardsManager.setIcon(0, str(dest))
    assert dest.exists()
