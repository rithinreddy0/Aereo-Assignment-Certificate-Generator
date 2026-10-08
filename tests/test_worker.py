import os
import subprocess
import sys

from filelock import FileLock


def test_worker_cli_and_single_worker_lock(client, payload):
    response = client.post("/api/jobs", json=payload)
    job_id = response.json()["id"]
    db = client.app.state.db
    env = {**os.environ, "CERT_DATA_DIR": str(db.data_dir)}
    lock = FileLock(str(db.data_dir / "worker.lock"))
    with lock:
        process = subprocess.run(
            [sys.executable, "-m", "app.worker", "--once"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert process.returncode == 1
        assert "Another worker" in process.stderr
    process = subprocess.run(
        [sys.executable, "-m", "app.worker", "--once"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "COMPLETED"
