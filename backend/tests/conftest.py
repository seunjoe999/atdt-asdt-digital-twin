import os
import tempfile

# Must be set before anything under app/ is imported, since Settings and
# TwinConfig read the environment at construction time (both are cached with
# lru_cache once built).
_tmp = tempfile.mkdtemp(prefix="atdt_test_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("CHROMA_DIR", f"{_tmp}/chroma")
os.environ.setdefault("DT_LLM__PROVIDER", "offline")
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)
