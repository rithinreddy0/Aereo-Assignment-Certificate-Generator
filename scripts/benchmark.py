"""Repeatable local benchmark; uses isolated temporary storage and real PDF generation."""

import argparse
import json
import tempfile
import time
import tracemalloc
from pathlib import Path

from app.db import Database
from app.schemas import JobCreate
from app.service import create_job, get_job
from app.worker import Worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipients", type=int, default=1000)
    parser.add_argument("--no-memory", action="store_true", help="Disable allocation tracing")
    args = parser.parse_args()
    if not 1 <= args.recipients <= 10_000:
        parser.error("Use 1 to 10000 recipients")
    with tempfile.TemporaryDirectory(prefix="certificate-benchmark-") as folder:
        db = Database(Path(folder))
        db.initialize()
        if not args.no_memory:
            tracemalloc.start()
        payload = JobCreate(
            certificate={
                "organization": "Aereo Academy",
                "course": "Python Development",
                "issued_on": "2026-10-08",
                "signatory": "Program Director",
            },
            recipients=[{"name": f"Participant {i}"} for i in range(args.recipients)],
        )
        started = time.perf_counter()
        job = create_job(db, payload, None)
        submission_seconds = time.perf_counter() - started
        worker = Worker(db)
        started = time.perf_counter()
        while worker.run_once():
            pass
        seconds = time.perf_counter() - started
        peak = None
        if not args.no_memory:
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        result = get_job(db, job.id)
        print(
            json.dumps(
                {
                    "recipients": args.recipients,
                    "status": result.status,
                    "succeeded": result.succeeded,
                    "failed": result.failed,
                    "submission_seconds": round(submission_seconds, 3),
                    "generation_seconds": round(seconds, 3),
                    "certificates_per_second": round(args.recipients / seconds, 2),
                    "peak_python_allocations_mib": round(peak / 1024**2, 2) if peak else None,
                    "pdf_storage_mib": round(
                        sum(
                            path.stat().st_size
                            for path in (db.data_dir / "certificates").rglob("*.pdf")
                        )
                        / 1024**2,
                        2,
                    ),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
