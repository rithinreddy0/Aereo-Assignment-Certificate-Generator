"""Durable single-worker queue. Run with: python -m app.worker."""

import argparse
import json
import logging
import signal
from threading import Event

from filelock import FileLock, Timeout

from app.config import Settings
from app.db import Database
from app.renderer import render_certificate
from app.schemas import CertificateInfo
from app.service import now

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, db: Database, renderer=render_certificate):
        self.db = db
        self.renderer = renderer

    def recover(self):
        # Only call while owning the worker lock. No other worker can still render these rows.
        with self.db.connect() as connection:
            connection.execute("UPDATE recipients SET status='QUEUED' WHERE status='PROCESSING'")

    def run_once(self) -> bool:
        """Process one recipient; durable commits bound restart loss to one PDF."""
        with self.db.connect() as connection:
            job = connection.execute(
                "SELECT * FROM jobs WHERE status IN ('QUEUED','RUNNING') "
                "ORDER BY created_at,id LIMIT 1"
            ).fetchone()
            if job is None:
                return False
            connection.execute("UPDATE jobs SET status='RUNNING' WHERE id=?", (job["id"],))
            recipient = connection.execute(
                "SELECT * FROM recipients WHERE job_id=? AND status='QUEUED' "
                "ORDER BY position LIMIT 1",
                (job["id"],),
            ).fetchone()
            if recipient is not None:
                connection.execute(
                    "UPDATE recipients SET status='PROCESSING' WHERE id=?", (recipient["id"],)
                )
        if recipient is None:
            self.finish_job(job["id"])
            return True
        error = None
        try:
            self.renderer(
                self.db.pdf_path(job["id"], recipient["id"]),
                CertificateInfo.model_validate(json.loads(job["certificate_json"])),
                recipient["name"],
                recipient["id"],
                recipient["reference"],
            )
        except Exception as exc:
            logger.exception("Certificate generation failed: %s", recipient["id"])
            error = (
                (str(exc) or "Invalid certificate data")[:500]
                if isinstance(exc, ValueError)
                else "Certificate generation failed; consult worker logs"
            )
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE recipients SET status=?,error=? WHERE id=?",
                ("FAILED" if error else "COMPLETED", error, recipient["id"]),
            )
            counter = "failed" if error else "succeeded"
            connection.execute(f"UPDATE jobs SET {counter}={counter}+1 WHERE id=?", (job["id"],))
        self.finish_job(job["id"])
        return True

    def finish_job(self, job_id: str):
        with self.db.connect() as connection:
            job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if job["succeeded"] + job["failed"] != job["total"]:
                return
            status = (
                "FAILED"
                if not job["succeeded"]
                else "COMPLETED_WITH_ERRORS"
                if job["failed"]
                else "COMPLETED"
            )
            connection.execute(
                "UPDATE jobs SET status=?,finished_at=? WHERE id=?", (status, now(), job_id)
            )
            logger.info("Job %s finished: %s", job_id, status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Drain queued work and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    db = Database(settings.data_dir)
    db.initialize()
    stopped = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    lock = FileLock(str(db.data_dir / "worker.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        parser.exit(1, "Another worker owns this data directory. Run only one worker.\n")
    try:
        worker = Worker(db)
        worker.recover()
        logger.info("Worker ready; database: %s", db.path)
        while not stopped.is_set():
            try:
                did_work = worker.run_once()
            except Exception:
                logger.exception("Worker infrastructure error; recovering before retry")
                stopped.wait(settings.poll_seconds)
                worker.recover()
                continue
            if not did_work:
                if args.once:
                    break
                stopped.wait(settings.poll_seconds)
    finally:
        lock.release()


if __name__ == "__main__":
    main()
