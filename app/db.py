"""Small SQLite persistence layer; short transactions keep reads responsive."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK(status IN
        ('QUEUED','RUNNING','COMPLETED','COMPLETED_WITH_ERRORS','FAILED')),
    certificate_json TEXT NOT NULL,
    total INTEGER NOT NULL CHECK(total > 0),
    succeeded INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    invalid INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    idempotency_key TEXT UNIQUE,
    request_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recipients (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    position INTEGER NOT NULL,
    name TEXT,
    email TEXT,
    reference TEXT,
    status TEXT NOT NULL CHECK(status IN ('QUEUED','PROCESSING','COMPLETED','INVALID','FAILED')),
    error TEXT,
    UNIQUE(job_id, position)
);
CREATE INDEX IF NOT EXISTS recipients_job_status ON recipients(job_id, status, position);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS jobs_history ON jobs(created_at DESC, id DESC);
"""


class Database:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.path = self.data_dir / "certificates.sqlite3"

    def initialize(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "certificates").mkdir(exist_ok=True)
        (self.data_dir / "archives").mkdir(exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def pdf_path(self, job_id: str, recipient_id: str) -> Path:
        # Callers use database-owned UUIDs, never user filenames.
        return self.data_dir / "certificates" / job_id / f"{recipient_id}.pdf"
