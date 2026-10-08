"""Job creation, validation, retrieval, and bounded-memory ZIP construction."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4
from zipfile import ZIP_STORED, ZipFile

from fastapi import HTTPException
from filelock import FileLock
from pydantic import ValidationError

from app.db import Database
from app.renderer import validate_template_text
from app.schemas import JobCreate, JobView, Recipient, RecipientView


def now() -> str:
    return datetime.now(UTC).isoformat()


def get_job(db: Database, job_id: str) -> JobView:
    with db.connect() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Job not found")
    return job_view(row)


def job_view(row) -> JobView:
    """Map a database row without opening another connection (also used by job history)."""
    done = row["succeeded"] + row["failed"]
    return JobView(
        id=row["id"],
        status=row["status"],
        total=row["total"],
        succeeded=row["succeeded"],
        failed=row["failed"],
        invalid=row["invalid"],
        pending=row["total"] - done,
        progress_percent=round(100 * done / row["total"], 2),
        created_at=row["created_at"],
        finished_at=row["finished_at"],
        certificate=json.loads(row["certificate_json"]),
    )


def create_job(db: Database, payload: JobCreate, key: str | None) -> JobView:
    validate_template_text(payload.certificate)
    canonical = payload.model_dump(mode="json")
    # Preserve hashes for pre-template clients and explicitly/defaulted Classic requests.
    if canonical["certificate"]["template"] == "classic":
        canonical["certificate"].pop("template")
    normalized = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    request_hash = hashlib.sha256(normalized.encode()).hexdigest()
    job_id = str(uuid4())
    rows = []
    seen_emails: set[str] = set()
    invalid = 0
    for index, raw in enumerate(payload.recipients):
        name = email = reference = error = None
        try:
            recipient = Recipient.model_validate(raw)
            name, email, reference = recipient.name, recipient.email, recipient.reference
            if email and email.casefold() in seen_emails:
                raise ValueError("Duplicate email within this job")
            if email:
                seen_emails.add(email.casefold())
        except ValidationError as exc:
            error = "; ".join(
                f"{'.'.join(map(str, entry['loc'])) or 'recipient'}: {entry['msg']}"
                for entry in exc.errors(include_url=False, include_input=False)
            )[:1000]
        except ValueError as exc:
            error = str(exc)
        if error:
            invalid += 1
        rows.append(
            (
                str(uuid4()),
                job_id,
                index,
                name,
                email,
                reference,
                "INVALID" if error else "QUEUED",
                error,
            )
        )
    created = now()
    status = "FAILED" if invalid == len(rows) else "QUEUED"
    try:
        with db.connect() as connection:
            connection.execute(
                """INSERT INTO jobs(id,status,certificate_json,total,failed,invalid,
                created_at,finished_at,idempotency_key,request_hash) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    job_id,
                    status,
                    payload.certificate.model_dump_json(),
                    len(rows),
                    invalid,
                    invalid,
                    created,
                    created if status == "FAILED" else None,
                    key,
                    request_hash,
                ),
            )
            connection.executemany(
                """INSERT INTO recipients(id,job_id,position,name,email,reference,status,error)
                VALUES(?,?,?,?,?,?,?,?)""",
                rows,
            )
    except sqlite3.IntegrityError:
        if key is None:
            raise
        with db.connect() as connection:
            previous = connection.execute(
                "SELECT id,request_hash FROM jobs WHERE idempotency_key=?", (key,)
            ).fetchone()
        if previous is None:
            raise
        if previous["request_hash"] != request_hash:
            raise HTTPException(
                409, "Idempotency-Key already used with a different request"
            ) from None
        job_id = previous["id"]
    return get_job(db, job_id)


def recipient_view(row) -> RecipientView:
    return RecipientView(
        id=row["id"],
        index=row["position"],
        name=row["name"],
        email=row["email"],
        reference=row["reference"],
        status=row["status"],
        error=row["error"],
        download_url=(
            f"/api/certificates/{row['id']}/download" if row["status"] == "COMPLETED" else None
        ),
    )


def build_archive(db: Database, job_id: str):
    job = get_job(db, job_id)
    if job.pending:
        raise HTTPException(409, "Wait until the job finishes before downloading its ZIP")
    if not job.succeeded:
        raise HTTPException(409, "This job has no successful certificates")
    path = db.data_dir / "archives" / f"{job.id}.zip"
    # ZIP is cached on disk; concurrent first requests cannot corrupt it.
    with FileLock(str(path) + ".lock", timeout=60):
        if not path.exists():
            temporary = path.with_suffix(".zip.tmp")
            try:
                with db.connect() as connection, ZipFile(temporary, "w", ZIP_STORED) as archive:
                    cursor = connection.execute(
                        "SELECT id FROM recipients WHERE job_id=? AND status='COMPLETED' "
                        "ORDER BY position",
                        (job.id,),
                    )
                    for row in cursor:
                        archive.write(db.pdf_path(job.id, row["id"]), f"{row['id']}.pdf")
                temporary.replace(path)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
    return path
