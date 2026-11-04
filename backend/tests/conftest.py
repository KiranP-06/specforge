import os
import pathlib
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("INLINE_JOBS", "true")
os.environ.setdefault("LLM_PROVIDER", "heuristic")
os.environ.setdefault("STORAGE_LOCAL_DIR", f"{_tmp}/data")
os.environ.setdefault("JWT_SECRET", "test-secret-key-that-is-long-enough-32b")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SAMPLE = pathlib.Path(__file__).resolve().parents[2] / "samples" / "campus_canteen_brief.md"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin(client):
    r = client.post("/api/auth/register", json={"email": "admin@example.com", "name": "Admin", "password": "password123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def sample_brief() -> str:
    return SAMPLE.read_text()


@pytest.fixture(scope="session")
def project(client, admin, sample_brief):
    r = client.post("/api/projects", json={"name": "Canteen", "brief_text": sample_brief}, headers=admin)
    assert r.status_code == 201
    pid = r.json()["id"]
    job = client.post(f"/api/projects/{pid}/generate", headers=admin)
    assert job.status_code == 202
    j = client.get(f"/api/jobs/{job.json()['id']}", headers=admin).json()
    assert j["status"] == "succeeded", j
    return pid
