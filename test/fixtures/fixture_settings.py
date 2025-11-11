import os
import random
import string

import pytest
from PySide6.QtCore import QCoreApplication, QSettings


@pytest.fixture(autouse=True)
def setAppName():
    randId = "".join(random.choices(string.ascii_letters + string.digits, k=4))
    QCoreApplication.setOrganizationName(f"AVocOrg_{randId}")
    QCoreApplication.setApplicationName(f"AVoc_{randId}")


@pytest.fixture(autouse=True)
def cleanUpSettings():
    yield
    settingsPath = QSettings().fileName()
    # Linux
    if os.path.exists(settingsPath):
        os.remove(settingsPath)
    settingsParentDir = os.path.dirname(settingsPath)
    # Try to remove empty parent directories
    if os.path.isdir(settingsParentDir):
        try:
            os.rmdir(settingsParentDir)
        except OSError:
            pass  # not empty, ignore
