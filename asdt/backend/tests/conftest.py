import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="asdt_test_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("ATDT_BASE_URL", "http://atdt.invalid")  # never actually called; client is monkeypatched

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)
