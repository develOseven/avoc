from unittest.mock import patch

import pytest

from ..mocks.mock_rvcr2 import MockRVCr2


@pytest.fixture(autouse=True)
def patchRVCr2():
    with patch("avoc.main.RVCr2", MockRVCr2):
        yield
