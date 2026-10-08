from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.config import Settings
from app.main import create_app
from app.worker import Worker


def drain(client, renderer=None):
    db = client.app.state.db
    worker = Worker(db, renderer) if renderer else Worker(db)
    worker.recover()
    while worker.run_once():
        pass


def submit(client, payload):
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 202, response.text
    return response.json()["id"]


def test_create_job_and_progress(client, payload):
    payload["recipients"] *= 2
    # Use distinct emails: duplicate rows are intentionally invalid.
    payload["recipients"][1] = {"name": "Second Person", "email": "second@example.com"}
    job_id = submit(client, payload)
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "QUEUED"
    assert job["pending"] == 2
    assert job["progress_percent"] == 0
    worker = Worker(client.app.state.db)
    worker.run_once()
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "RUNNING"
    assert job["succeeded"] == 1
    assert job["progress_percent"] == 50
    worker.run_once()
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "COMPLETED"
    assert job["progress_percent"] == 100
    assert job["finished_at"] is not None


@pytest.mark.parametrize(
    "change",
    [
        {"recipients": []},
        {"recipients": "wrong-type"},
        {"unexpected": True},
        {"certificate": {"organization": "missing fields"}},
    ],
)
def test_invalid_envelope(client, payload, change):
    payload.update(change)
    assert client.post("/api/jobs", json=payload).status_code == 422


@pytest.mark.parametrize(
    "bad",
    [
        {"name": ""},
        {"name": 123},
        {"name": "Good Name", "email": "not-an-email"},
        {"name": "A" * 121},
        {"name": "Bad\nName"},
        {"name": "Test", "unknown": 1},
        None,
        "bad-row",
        {"email": "a@example.com"},
    ],
)
def test_individual_validation_isolation(client, payload, bad):
    payload["recipients"].append(bad)
    job_id = submit(client, payload)
    drain(client)
    job = client.get(f"/api/jobs/{job_id}").json()
    assert (job["succeeded"], job["failed"], job["invalid"]) == (1, 1, 1)
    assert job["status"] == "COMPLETED_WITH_ERRORS"
    rows = client.get(f"/api/jobs/{job_id}/certificates?status=INVALID").json()
    assert rows["total"] == 1
    assert rows["items"][0]["index"] == 1
    assert rows["items"][0]["error"]
    assert rows["items"][0]["download_url"] is None


def test_all_invalid_finishes_without_worker(client, payload):
    payload["recipients"] = [{"name": ""}, None]
    job_id = submit(client, payload)
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "FAILED"
    assert job["pending"] == 0
    assert job["progress_percent"] == 100
    assert client.get(f"/api/jobs/{job_id}/download").status_code == 409


def test_duplicate_email(client, payload):
    payload["recipients"].append({"name": "Duplicate", "email": "RITHI@example.com"})
    job_id = submit(client, payload)
    assert client.get(f"/api/jobs/{job_id}").json()["invalid"] == 1


def test_generation_failure_isolation(client, payload):
    from app.renderer import render_certificate

    payload["recipients"] = [{"name": "First"}, {"name": "Failure"}, {"name": "Last"}]
    job_id = submit(client, payload)

    def renderer(path, info, name, certificate_id, reference):
        if name == "Failure":
            raise RuntimeError("Simulated rendering problem")
        render_certificate(path, info, name, certificate_id, reference)

    drain(client, renderer)
    job = client.get(f"/api/jobs/{job_id}").json()
    assert (job["succeeded"], job["failed"], job["pending"]) == (2, 1, 0)
    rows = client.get(f"/api/jobs/{job_id}/certificates").json()["items"]
    assert [row["status"] for row in rows] == ["COMPLETED", "FAILED", "COMPLETED"]
    assert rows[1]["error"]
    assert client.get(f"/api/certificates/{rows[1]['id']}/download").status_code == 409


def test_pdf_and_zip_download(client, payload):
    job_id = submit(client, payload)
    assert client.get(f"/api/jobs/{job_id}/download").status_code == 409
    row = client.get(f"/api/jobs/{job_id}/certificates").json()["items"][0]
    url = f"/api/certificates/{row['id']}/download"
    assert client.get(url).status_code == 409
    drain(client)
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    reader = PdfReader(BytesIO(response.content))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    for value in ("Rithi Aluri", "Python Backend Development", "Aereo Academy", row["id"]):
        assert value in text
    archive = client.get(f"/api/jobs/{job_id}/download")
    assert archive.status_code == 200
    with ZipFile(BytesIO(archive.content)) as zip_file:
        assert zip_file.namelist() == [f"{row['id']}.pdf"]
        assert zip_file.read(zip_file.namelist()[0]) == response.content
    assert client.get(f"/api/jobs/{job_id}/download").content == archive.content


def test_missing_download_file(client, payload):
    job_id = submit(client, payload)
    drain(client)
    row = client.get(f"/api/jobs/{job_id}/certificates").json()["items"][0]
    client.app.state.db.pdf_path(job_id, row["id"]).unlink()
    assert client.get(row["download_url"]).status_code == 410
    assert client.get(f"/api/jobs/{job_id}/download").status_code == 410


def test_pagination_and_filtering(client, payload):
    payload["recipients"] = [{"name": f"Person {i}"} for i in range(5)] + [None]
    job_id = submit(client, payload)
    page = client.get(f"/api/jobs/{job_id}/certificates?limit=2&offset=2").json()
    assert page["total"] == 6
    assert [row["index"] for row in page["items"]] == [2, 3]
    assert client.get(f"/api/jobs/{job_id}/certificates?limit=501").status_code == 422
    assert client.get(f"/api/jobs/{job_id}/certificates?status=unknown").status_code == 422


def test_idempotency_and_conflict(client, payload):
    headers = {"Idempotency-Key": "repeat-me"}
    first = client.post("/api/jobs", json=payload, headers=headers)
    second = client.post("/api/jobs", json=payload, headers=headers)
    assert first.json()["id"] == second.json()["id"]
    payload["recipients"][0]["name"] = "Changed"
    assert client.post("/api/jobs", json=payload, headers=headers).status_code == 409


def test_concurrent_idempotency(client, payload):
    def post(_):
        return client.post("/api/jobs", json=payload, headers={"Idempotency-Key": "concurrent"})

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(post, range(4)))
    assert all(response.status_code == 202 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1


def test_restart_recovery(client, payload):
    job_id = submit(client, payload)
    db = client.app.state.db
    with db.connect() as connection:
        connection.execute("UPDATE jobs SET status='RUNNING' WHERE id=?", (job_id,))
        connection.execute("UPDATE recipients SET status='PROCESSING' WHERE job_id=?", (job_id,))
    drain(client)
    drain(client)
    assert client.get(f"/api/jobs/{job_id}").json()["succeeded"] == 1


def test_restart_after_pdf_written(client, payload):
    from app.renderer import render_certificate
    from app.schemas import CertificateInfo

    job_id = submit(client, payload)
    db = client.app.state.db
    row = client.get(f"/api/jobs/{job_id}/certificates").json()["items"][0]
    path = db.pdf_path(job_id, row["id"])
    render_certificate(
        path, CertificateInfo.model_validate(payload["certificate"]), row["name"], row["id"]
    )
    with db.connect() as connection:
        connection.execute("UPDATE recipients SET status='PROCESSING' WHERE job_id=?", (job_id,))
    drain(client)
    assert client.get(f"/api/jobs/{job_id}").json()["succeeded"] == 1
    assert not path.with_suffix(".pdf.tmp").exists()


def test_unknown_and_malformed_ids(client):
    assert client.get(f"/api/jobs/{uuid4()}").status_code == 404
    assert client.get(f"/api/certificates/{uuid4()}/download").status_code == 404
    assert client.get("/api/jobs/not-a-uuid").status_code == 422
    assert client.get("/health").json()["status"] == "ok"


def test_limits_and_api_key(tmp_path, payload):
    settings = Settings(data_dir=tmp_path, max_recipients=1, api_key="secret")
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/jobs", json=payload).status_code == 401
        headers = {"X-API-Key": "secret"}
        assert client.post("/api/jobs", json=payload, headers=headers).status_code == 202
        payload["recipients"].append({"name": "Second"})
        assert client.post("/api/jobs", json=payload, headers=headers).status_code == 422
    with TestClient(create_app(Settings(data_dir=tmp_path, max_body_bytes=10))) as client:
        assert client.post("/api/jobs", json=payload).status_code == 413
        assert client.post("/api/jobs", content=iter([b"x" * 6, b"y" * 6])).status_code == 413


def test_supported_accented_name(client, payload):
    payload["recipients"] = [{"name": "Renée Müller"}]
    job_id = submit(client, payload)
    drain(client)
    row = client.get(f"/api/jobs/{job_id}/certificates").json()["items"][0]
    text = PdfReader(BytesIO(client.get(row["download_url"]).content)).pages[0].extract_text()
    assert "Renée Müller" in text


def test_unsupported_glyph_is_clear_failure(client, payload):
    payload["recipients"].append({"name": "Person 🎉"})
    job_id = submit(client, payload)
    drain(client)
    job = client.get(f"/api/jobs/{job_id}").json()
    assert (job["succeeded"], job["failed"]) == (1, 1)
    row = client.get(f"/api/jobs/{job_id}/certificates?status=FAILED").json()["items"][0]
    assert "unsupported" in row["error"]


def test_unsupported_shared_text_rejects_job(client, payload):
    payload["certificate"]["organization"] = "Organization 🎉"
    assert client.post("/api/jobs", json=payload).status_code == 422


def test_invalid_date(client, payload):
    payload["certificate"]["issued_on"] = "2026-02-30"
    assert client.post("/api/jobs", json=payload).status_code == 422
