from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.worker import Worker


def test_frontend_and_configuration(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Folio" in response.text
    assert "certificate-form" in response.text
    for file in ("style.css", "app.js", "favicon.svg"):
        assert client.get(f"/static/{file}").status_code == 200
    config = client.get("/ui-config").json()
    assert config["max_recipients"] == 10000
    assert config["authentication_required"] is False


def test_paginated_history_and_attention_filter(client, payload):
    payload["recipients"] = [{"name": "Valid"}, {"name": ""}, {"name": "Unsupported 🎉"}]
    first = client.post("/api/jobs", json=payload).json()
    second = client.post("/api/jobs", json=payload).json()
    history = client.get("/api/jobs?limit=1").json()
    assert history["total"] == 2
    assert history["items"][0]["id"] == second["id"]
    assert client.get("/api/jobs?limit=1&offset=1").json()["items"][0]["id"] == first["id"]
    worker = Worker(client.app.state.db)
    while worker.run_once():
        pass
    attention = client.get(f"/api/jobs/{first['id']}/certificates?attention=true").json()
    assert attention["total"] == 2
    assert {row["status"] for row in attention["items"]} == {"FAILED", "INVALID"}
    assert (
        client.get(f"/api/jobs/{first['id']}/certificates?attention=true&status=FAILED").status_code
        == 422
    )


def test_inline_preview_and_head(client, payload):
    job = client.post("/api/jobs", json=payload).json()
    Worker(client.app.state.db).run_once()
    row = client.get(f"/api/jobs/{job['id']}/certificates").json()["items"][0]
    url = f"/api/certificates/{row['id']}/preview"
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.content.startswith(b"%PDF")
    head = client.head(url)
    assert head.status_code == 200
    assert not head.content
    assert head.headers["content-type"] == "application/pdf"


def test_browser_session_protects_streaming_downloads(tmp_path, payload):
    with TestClient(create_app(Settings(data_dir=tmp_path, api_key="private-key"))) as client:
        assert client.get("/api/jobs").status_code == 401
        assert client.post("/ui-session").status_code == 401
        response = client.post("/ui-session", headers={"X-API-Key": "private-key"})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        assert "private-key" not in cookie
        assert client.get("/api/jobs").status_code == 200
        # An explicitly wrong header is rejected even when a browser session exists.
        assert client.get("/api/jobs", headers={"X-API-Key": "wrong"}).status_code == 401
        job = client.post("/api/jobs", json=payload).json()
        Worker(client.app.state.db).run_once()
        assert client.get(f"/api/jobs/{job['id']}/download").status_code == 200
        client.delete("/ui-session")
        assert client.get("/api/jobs").status_code == 401
        assert client.get(f"/api/jobs/{job['id']}/download").status_code == 401
