"""Exercise the cloud worker and persistent downloads after losing the local cache."""

import os
import time
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.config import Settings
from app.main import create_app


@pytest.mark.parametrize("postgres", [False, True])
def test_embedded_worker_and_restart(tmp_path, payload, postgres):
    database_url = os.getenv("TEST_DATABASE_URL", "") if postgres else ""
    if postgres and not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run the PostgreSQL integration test")
    settings = Settings(
        data_dir=tmp_path, database_url=database_url, embedded_worker=True, poll_seconds=0.05
    )
    key = str(uuid4())
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/jobs", json=payload, headers={"Idempotency-Key": key})
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["pending"] == 0:
                break
            time.sleep(0.05)
        assert job["status"] == "COMPLETED"
        assert client.get("/health").json()["worker_required"] is False
        results = client.get(f"/api/jobs/{job_id}/certificates").json()
        recipient_id = results["items"][0]["id"]
        pdf_url = results["items"][0]["download_url"]
        original = client.get(pdf_url).content
        assert len(PdfReader(BytesIO(original)).pages) == 1
        assert (
            client.post("/api/jobs", json=payload, headers={"Idempotency-Key": key}).json()["id"]
            == job_id
        )
        conflicting = {**payload, "recipients": [{"name": "Different Person"}]}
        assert (
            client.post("/api/jobs", json=conflicting, headers={"Idempotency-Key": key}).status_code
            == 409
        )
        if postgres:
            client.app.state.db.pdf_path(job_id, recipient_id).unlink()
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(pdf_url).content == original
        archive = restarted.get(f"/api/jobs/{job_id}/download")
        assert archive.status_code == 200
        with ZipFile(BytesIO(archive.content)) as zipped:
            assert zipped.read(f"{recipient_id}.pdf") == original
