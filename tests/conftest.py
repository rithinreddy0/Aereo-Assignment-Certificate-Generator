import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        yield client


@pytest.fixture
def payload():
    return {
        "certificate": {
            "organization": "Aereo Academy",
            "course": "Python Backend Development",
            "issued_on": "2026-10-08",
            "signatory": "Vidya Pawar",
        },
        "recipients": [{"name": "Rithi Aluri", "email": "rithi@example.com"}],
    }
