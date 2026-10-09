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
    def __init__(self, data_dir: Path, database_url: str = ""):
        self.data_dir = data_dir.resolve()
        self.path = self.data_dir / "certificates.sqlite3"
        self.database_url = database_url

    def initialize(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "certificates").mkdir(exist_ok=True)
        (self.data_dir / "archives").mkdir(exist_ok=True)
        with self.connect() as connection:
            if self.database_url:
                # Serialize schema creation during overlapping deployments.
                connection.execute("SELECT pg_advisory_xact_lock(7821041)")
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS certificate_files ("
                    "recipient_id TEXT PRIMARY KEY REFERENCES recipients(id), "
                    "content BYTEA NOT NULL)"
                )
            else:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        if self.database_url:
            import psycopg

            from app.postgres import Connection, hybrid_row

            with psycopg.connect(
                self.database_url, row_factory=hybrid_row, connect_timeout=15
            ) as raw:
                yield Connection(raw)
            return
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

    @contextmanager
    def worker_lock(self):
        from filelock import FileLock, Timeout

        with FileLock(str(self.data_dir / "worker.lock"), timeout=0):
            if self.database_url:
                # Transaction lock works with Neon pooler connections and across deploys.
                with self.connect() as connection:
                    acquired = connection.execute(
                        "SELECT pg_try_advisory_xact_lock(7821042)"
                    ).fetchone()[0]
                    if not acquired:
                        raise Timeout("database worker lock")
                    yield
            else:
                yield

    def store_pdf(self, job_id: str, recipient_id: str, connection):
        if self.database_url:
            connection.execute(
                "INSERT INTO certificate_files(recipient_id,content) VALUES(?,?) "
                "ON CONFLICT(recipient_id) DO UPDATE SET content=excluded.content",
                (recipient_id, self.pdf_path(job_id, recipient_id).read_bytes()),
            )

    def ensure_pdf(self, job_id: str, recipient_id: str) -> Path:
        path = self.pdf_path(job_id, recipient_id)
        if not path.exists() and self.database_url:
            from filelock import FileLock

            path.parent.mkdir(parents=True, exist_ok=True)
            with FileLock(str(path) + ".lock", timeout=60):
                if not path.exists():
                    with self.connect() as connection:
                        row = connection.execute(
                            "SELECT content FROM certificate_files WHERE recipient_id=?",
                            (recipient_id,),
                        ).fetchone()
                    if row is not None:
                        temporary = path.with_suffix(".pdf.tmp")
                        temporary.write_bytes(bytes(row["content"]))
                        temporary.replace(path)
        return path
