from pathlib import Path

import pytest

from app.worker import Worker


def test_reference_covers_public_endpoints_and_guide_links(client):
    root = Path(__file__).resolve().parents[1]
    reference = (root / "docs" / "API_REFERENCE.md").read_text(encoding="utf-8")
    technical = (root / "docs" / "TECHNICAL_GUIDE.md").read_text(encoding="utf-8")
    schema = client.get("/openapi.json").json()
    for path, operations in schema["paths"].items():
        for method in operations:
            if method in {"get", "post"}:
                assert f"{method.upper()} {path}" in reference
    assert "ReportLab" in technical and "PDF.js" in technical
    page = client.get("/docs").text
    assert 'id="understand"' in page
    assert 'id="payload"' in page
    assert "Read a job response correctly" in page
    assert "Shared certificate fields" in page


@pytest.mark.parametrize("example_name,invalid_count", [("all-valid", 0), ("mixed-results", 1)])
def test_swagger_examples_match_actual_api_behavior(client, example_name, invalid_count):
    schema = client.get("/openapi.json").json()
    post = schema["paths"]["/api/jobs"]["post"]
    examples = post["requestBody"]["content"]["application/json"]["examples"]
    response = client.post("/api/jobs", json=examples[example_name]["value"])
    assert response.status_code == 202
    job = response.json()
    assert job["invalid"] == invalid_count
    worker = Worker(client.app.state.db)
    while worker.run_once():
        pass
    finished = client.get(f"/api/jobs/{job['id']}").json()
    assert finished["succeeded"] == 2
    assert finished["failed"] == invalid_count
    assert finished["pending"] == 0
    assert finished["progress_percent"] == 100
    assert finished["status"] == ("COMPLETED_WITH_ERRORS" if invalid_count else "COMPLETED")


def test_openapi_documents_auth_errors_and_binary_responses(client):
    schema = client.get("/openapi.json").json()
    for path, operations in schema["paths"].items():
        if path.startswith("/api/"):
            for operation in operations.values():
                assert "401" in operation["responses"]
    assert "APIErrorResponse" in schema["components"]["schemas"]
    for path, media_type in (
        ("/api/certificates/{certificate_id}/download", "application/pdf"),
        ("/api/certificates/{certificate_id}/preview", "application/pdf"),
        ("/api/jobs/{job_id}/download", "application/zip"),
    ):
        assert media_type in schema["paths"][path]["get"]["responses"]["200"]["content"]
