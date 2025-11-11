from pathlib import Path

from voiceconversion.data.imported_model_info import (
    ImportedModelInfo,
    RVCImportedModelInfo,
)
from voiceconversion.imported_model_info_manager import ImportedModelInfoManager
from voiceconversion.utils.import_model_params import ImportModelParams


def mock_import_model(
    imported_model_info_manager: ImportedModelInfoManager,
    params: ImportModelParams,
    imported_model_info: ImportedModelInfo | None,
) -> ImportedModelInfo | None:
    if imported_model_info is None:
        id, storage_dir = imported_model_info_manager.new_id()
    else:
        id = imported_model_info.id
        storage_dir = imported_model_info.storageDir

    imported_model_info = RVCImportedModelInfo()
    imported_model_info.id = id
    imported_model_info.storageDir = storage_dir
    imported_model_info.voiceChangerType = params.voice_changer_type
    for f in params.files:
        if f.kind == "rvcModel":
            imported_model_info.name = Path(f.name).stem
            break

    imported_model_info_manager.save(imported_model_info)

    return imported_model_info
