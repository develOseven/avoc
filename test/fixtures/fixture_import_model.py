from unittest.mock import patch

import pytest

from ..mocks.mock_import_model import mock_import_model


@pytest.fixture(autouse=True)
def patch_import_model():
    with patch("avoc.main.import_model", mock_import_model):
        yield
