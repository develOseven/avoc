from voiceconversion.data.imported_model_info import RVCImportedModelInfo
from voiceconversion.imported_model_info_manager import ImportedModelInfoManager


def newInfo(manager: ImportedModelInfoManager, name="model"):
    id, storage_dir = manager.new_id()
    info = RVCImportedModelInfo(
        id=id,
        storageDir=storage_dir,
        name=name,
        voiceChangerType="RVC",
    )
    manager.save(info)
    return info
