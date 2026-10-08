import hashlib
import json
from io import BytesIO

import pytest
from pypdf import PdfReader

from app.schemas import JobCreate
from app.worker import Worker


def test_template_catalogue(client):
    response = client.get("/api/templates")
    assert response.status_code == 200
    catalogue = response.json()
    assert catalogue["default"] == "classic"
    assert [item["id"] for item in catalogue["items"]] == ["classic", "modern", "minimal"]
    assert all(item["page_format"] == "A4 landscape" for item in catalogue["items"])


@pytest.mark.parametrize("template", ["classic", "modern", "minimal"])
def test_selected_template_persists_and_generates(client, payload, template):
    payload["certificate"]["template"] = template
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 202
    job = response.json()
    assert job["certificate"]["template"] == template
    Worker(client.app.state.db).run_once()
    finished = client.get(f"/api/jobs/{job['id']}").json()
    assert finished["status"] == "COMPLETED"
    assert finished["certificate"]["template"] == template
    recipient = client.get(f"/api/jobs/{job['id']}/certificates").json()["items"][0]
    pdf = client.get(recipient["download_url"])
    reader = PdfReader(BytesIO(pdf.content))
    assert len(reader.pages) == 1
    assert "Rithi Aluri" in reader.pages[0].extract_text()
    # Verify the worker actually selected a different vector background, not just job metadata.
    commands = reader.pages[0].get_contents().get_data()
    if template == "modern":
        assert b"0 490" in commands
    elif template == "minimal":
        assert b"35 35" in commands
    else:
        assert b"26 26" in commands


def test_unknown_template_rejected_without_creating_job(client, payload):
    payload["certificate"]["template"] = "user-uploaded-code"
    assert client.post("/api/jobs", json=payload).status_code == 422
    assert client.get("/api/jobs").json()["total"] == 0


def test_template_idempotency_and_legacy_hash(client, payload):
    headers = {"Idempotency-Key": "original-key"}
    original = client.post("/api/jobs", json=payload, headers=headers).json()
    canonical = JobCreate.model_validate(payload).model_dump(mode="json")
    canonical["certificate"].pop("template")
    legacy_hash = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    with client.app.state.db.connect() as db:
        stored = db.execute(
            "SELECT request_hash FROM jobs WHERE id=?", (original["id"],)
        ).fetchone()
    assert stored["request_hash"] == legacy_hash
    payload["certificate"]["template"] = "classic"
    assert client.post("/api/jobs", json=payload, headers=headers).json()["id"] == original["id"]
    payload["certificate"]["template"] = "modern"
    assert client.post("/api/jobs", json=payload, headers=headers).status_code == 409


def test_legacy_job_defaults_to_classic(client, payload):
    original = client.post("/api/jobs", json=payload).json()
    legacy = original["certificate"]
    legacy.pop("template")
    with client.app.state.db.connect() as db:
        db.execute(
            "UPDATE jobs SET certificate_json=? WHERE id=?", (json.dumps(legacy), original["id"])
        )
    assert client.get(f"/api/jobs/{original['id']}").json()["certificate"]["template"] == "classic"
    Worker(client.app.state.db).run_once()
    assert client.get(f"/api/jobs/{original['id']}").json()["status"] == "COMPLETED"


def test_documentation_and_openapi(client):
    page = client.get("/docs")
    assert page.status_code == 200
    assert "INTERACTIVE REFERENCE" in page.text
    assert "cdn" not in page.text.lower()
    for asset in ("docs.css", "docs.js", "vendor/swagger-ui.css", "vendor/swagger-ui-bundle.js"):
        assert client.get(f"/static/{asset}").status_code == 200
    schema = client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["ApiKey"]["name"] == "X-API-Key"
    template = schema["components"]["schemas"]["CertificateInfo"]["properties"]["template"]
    assert template["enum"] == ["classic", "modern", "minimal"]
    assert template["default"] == "classic"
    assert "examples" in schema["components"]["schemas"]["JobCreate"]
    assert "413" in schema["paths"]["/api/jobs"]["post"]["responses"]
