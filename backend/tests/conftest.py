import json
import os
import tempfile
from pathlib import Path

# Configure BEFORE the app is imported: isolated DB, no network models.
_tmp = Path(tempfile.mkdtemp())
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ["LLM_PROVIDER"] = "rules"
os.environ["LLM_FALLBACK_PROVIDER"] = ""
os.environ["UPLOAD_DIR"] = str(_tmp / "uploads")
os.environ["AUDIO_ENGINES"] = "whisper"  # never call Gemini from tests
os.environ["OCR_ENGINES"] = "tesseract"
os.environ["GEMINI_API_KEY"] = ""
os.environ["DEMO_PASSWORD"] = "test-pass"
os.environ["JWT_SECRET"] = "test-secret-for-pytest-only-0123456789"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
CASES_FILE = BACKEND / "data" / "synthetic_cases" / "phase1_cases.json"
CASES2_FILE = BACKEND / "data" / "synthetic_cases" / "phase2_cases.json"
SAMPLES = BACKEND / "data" / "sample_reports"


@pytest.fixture(scope="session", autouse=True)
def sample_reports():
    if not (SAMPLES / "cbc_dengue.png").exists():
        from scripts.make_samples import main as make
        make()
    return SAMPLES


@pytest.fixture(scope="session")
def synthetic_cases2():
    return json.loads(CASES2_FILE.read_text(encoding="utf-8"))


def login(c: TestClient, username: str) -> dict:
    r = c.post("/api/auth/login", json={"username": username, "password": "test-pass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def client():
    """Signed in as the demo doctor by default."""
    with TestClient(app) as c:
        c.headers.update(login(c, "dr.mehra"))
        yield c


@pytest.fixture(scope="session")
def as_role(client):
    """Headers for another demo account: as_role('intake') / 'nurse' / 'admin'."""
    users = {"doctor": "dr.mehra", "nurse": "sr.thomas", "intake": "desk.ravi", "admin": "admin"}
    cache: dict[str, dict] = {}

    def get(role: str) -> dict:
        if role not in cache:
            cache[role] = login(client, users[role])
        return cache[role]

    return get


@pytest.fixture(scope="session")
def synthetic_cases():
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))
