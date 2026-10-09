"""HTTP API. PDF work belongs to the separately running worker."""

import asyncio
import hashlib
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event, Thread
from typing import Annotated
from uuid import UUID

from fastapi import Body, Cookie, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from filelock import Timeout

from app.config import Settings
from app.db import Database
from app.schemas import (
    JOB_REQUEST_EXAMPLES,
    APIErrorResponse,
    JobCreate,
    JobPage,
    JobView,
    RecipientPage,
    RecipientStatus,
)
from app.service import build_archive, create_job, get_job, job_view, recipient_view
from app.templates import TEMPLATES, TemplateCatalogue


class BodyLimitMiddleware:
    """Bound JSON ingestion even when Content-Length is absent or incorrect."""

    def __init__(self, app, limit: int):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.limit:
                response = JSONResponse({"detail": "Request body is too large"}, status_code=413)
                return await response(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.data_dir, settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        db.initialize()
        stopped = Event()
        thread = None
        if settings.embedded_worker:
            from app.worker import run_worker

            thread = Thread(
                target=run_worker, args=(db, stopped, settings.poll_seconds), daemon=True
            )
            thread.start()
        try:
            yield
        finally:
            stopped.set()
            if thread is not None:
                await asyncio.to_thread(thread.join, 25)

    app = FastAPI(
        title="Bulk Certificate Generator",
        version="1.1.0",
        docs_url=None,
        lifespan=lifespan,
        description="A durable, asynchronous batch API backed by SQLite "
        "and a separate PDF worker.\n\n"
        "1. Discover presets with **GET /api/templates**.\n"
        "2. Submit certificate details and recipients with **POST /api/jobs** (202 Accepted).\n"
        "3. Poll **GET /api/jobs/{job_id}** until pending is zero.\n"
        "4. List recipient results, preview individual PDFs, or download a batch ZIP.\n\n"
        "Run `python -m app.worker` separately: starting the API alone does not generate PDFs. "
        "No authentication is required locally unless CERT_API_KEY is configured. "
        "Then use **Authorize** to supply X-API-Key. "
        "See the guide above for validation and status semantics.",
        openapi_tags=[
            {"name": "Templates", "description": "Discover the supported PDF designs and default."},
            {"name": "Jobs", "description": "Submit durable batches and track their progress."},
            {
                "name": "Certificates",
                "description": "Inspect individual successes and errors; preview real PDFs.",
            },
            {
                "name": "Downloads",
                "description": "Retrieve PDFs or a ZIP of the successful certificates.",
            },
            {
                "name": "Health",
                "description": "Check API/database connectivity, not worker liveness.",
            },
        ],
    )
    app.state.db = db
    app.add_middleware(BodyLimitMiddleware, limit=settings.max_body_bytes)
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def frontend():
        return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/docs", include_in_schema=False)
    def documentation():
        return FileResponse(static_dir / "docs.html", headers={"Cache-Control": "no-cache"})

    @app.get("/ui-config", include_in_schema=False)
    def ui_config():
        return {
            "max_recipients": settings.max_recipients,
            "max_body_bytes": settings.max_body_bytes,
            "authentication_required": bool(settings.api_key),
        }

    def browser_token():
        # A separate browser credential: the raw API key is never written into a cookie.
        return hmac.new(
            settings.api_key.encode(), b"folio-browser-session-v1", hashlib.sha256
        ).hexdigest()

    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, scheme_name="ApiKey")

    def authenticate(
        x_api_key: Annotated[str | None, Depends(api_key_header)] = None,
        folio_session: Annotated[str | None, Cookie(include_in_schema=False)] = None,
    ):
        if not settings.api_key:
            return
        valid = (
            hmac.compare_digest(x_api_key.encode(), settings.api_key.encode())
            if x_api_key is not None
            else hmac.compare_digest((folio_session or "").encode(), browser_token().encode())
        )
        if not valid:
            raise HTTPException(401, "Missing or invalid X-API-Key")

    @app.post("/ui-session", include_in_schema=False)
    def browser_session(request: Request, x_api_key: Annotated[str | None, Header()] = None):
        # Allows the browser to stream native downloads without buffering a large ZIP in JS.
        authenticate(x_api_key=x_api_key, folio_session=None)
        response = JSONResponse({"connected": True})
        if settings.api_key:
            response.set_cookie(
                "folio_session",
                browser_token(),
                httponly=True,
                samesite="strict",
                secure=request.url.scheme == "https",
            )
        else:
            response.delete_cookie("folio_session")
        return response

    @app.delete("/ui-session", include_in_schema=False)
    def clear_browser_session():
        response = JSONResponse({"connected": False})
        response.delete_cookie("folio_session")
        return response

    secured = [Depends(authenticate)]
    auth_errors = {
        401: {
            "model": APIErrorResponse,
            "description": "Missing or invalid API key when CERT_API_KEY is configured.",
        }
    }
    unknown_job = {404: {"model": APIErrorResponse, "description": "Unknown job UUID."}}

    @app.get(
        "/api/templates",
        response_model=TemplateCatalogue,
        dependencies=secured,
        tags=["Templates"],
        summary="List available certificate templates",
        responses={
            **auth_errors,
            200: {
                "content": {
                    "application/json": {
                        "example": TemplateCatalogue(items=list(TEMPLATES)).model_dump()
                    }
                }
            },
        },
    )
    def template_catalogue():
        """Use an item's **id** as `certificate.template` when creating a job.

        All presets share the same validated fields and A4 landscape PDF format.
        Omitting the template selects Classic. Templates are fixed designs, not user-uploaded code.
        """
        return TemplateCatalogue(items=list(TEMPLATES))

    @app.get(
        "/api/jobs",
        response_model=JobPage,
        dependencies=secured,
        tags=["Jobs"],
        summary="List generation jobs",
        responses=auth_errors,
    )
    def job_history(
        limit: Annotated[int, Query(ge=1, le=100, description="Maximum jobs in this page.")] = 25,
        offset: Annotated[int, Query(ge=0, description="Number of newest-first jobs to skip.")] = 0,
    ):
        """List batches newest first with limit/offset pagination and the selected template."""
        with db.connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return JobPage(
            items=[job_view(row) for row in rows], total=total, limit=limit, offset=offset
        )

    @app.get("/health", tags=["Health"])
    def health():
        """A database connectivity probe. `worker_required: true` is not a worker heartbeat."""
        with db.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return {"status": "ok", "worker_required": not settings.embedded_worker}

    @app.post(
        "/api/jobs",
        response_model=JobView,
        status_code=202,
        dependencies=secured,
        tags=["Jobs"],
        summary="Create a bulk certificate job",
        responses={
            **auth_errors,
            409: {
                "model": APIErrorResponse,
                "description": "Key was used for a different payload.",
            },
            413: {
                "model": APIErrorResponse,
                "description": "Body exceeds its limit (default 8 MiB).",
            },
            422: {
                "model": APIErrorResponse,
                "description": "Invalid certificate/template, empty batch, or too many recipients.",
            },
        },
    )
    def submit_job(
        payload: Annotated[JobCreate, Body(openapi_examples=JOB_REQUEST_EXAMPLES)],
        idempotency_key: Annotated[
            str | None,
            Header(
                min_length=1,
                max_length=128,
                description="Optional safe-retry key. Same payload returns the original job; "
                "different data/template with the same key returns 409. Keys do not expire.",
            ),
        ] = None,
    ):
        """Persist the batch and return immediately; generation runs in the separate worker.

        - Set `certificate.template` to **classic**, **modern**, or **minimal** (default classic).
        - Invalid recipient rows and duplicate emails are recorded as INVALID; valid rows still run.
        - Shared certificate errors reject the entire request with 422, before a job is created.
        - Optional **Idempotency-Key** makes identical retries return the same job (still HTTP 202).
          Use a new key for each request; changing a template counts as changing the payload.
        - `failed` includes `invalid`. `pending = total - succeeded - failed`.
          An all-invalid batch is immediately FAILED with 100% progress.
        """
        if len(payload.recipients) > settings.max_recipients:
            raise HTTPException(422, f"Maximum {settings.max_recipients} recipients per job")
        try:
            return create_job(db, payload, idempotency_key)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get(
        "/api/jobs/{job_id}",
        response_model=JobView,
        dependencies=secured,
        tags=["Jobs"],
        summary="Track job status and progress",
        responses={**auth_errors, **unknown_job},
    )
    def job_information(job_id: UUID):
        """Poll approximately every two seconds until `pending == 0`.

        QUEUED → RUNNING → COMPLETED / COMPLETED_WITH_ERRORS / FAILED.
        COMPLETED means every recipient succeeded; COMPLETED_WITH_ERRORS means a mix of successes
        and failures; FAILED means no successful certificate. Progress counts failures as processed.
        """
        return get_job(db, str(job_id))

    @app.get(
        "/api/jobs/{job_id}/certificates",
        response_model=RecipientPage,
        dependencies=secured,
        tags=["Certificates"],
        summary="List recipient outcomes",
        responses={
            **auth_errors,
            **unknown_job,
            422: {
                "model": APIErrorResponse,
                "description": "Invalid query/UUID, or attention combined with status.",
            },
        },
    )
    def job_certificates(
        job_id: UUID,
        limit: Annotated[
            int, Query(ge=1, le=500, description="Maximum matching rows per page.")
        ] = 100,
        offset: Annotated[
            int, Query(ge=0, description="Matching rows to skip, in input order.")
        ] = 0,
        status: Annotated[
            RecipientStatus | None,
            Query(description="Exact recipient state. Cannot be combined with attention=true."),
        ] = None,
        attention: Annotated[
            bool, Query(description="Only INVALID and FAILED rows. Mutually exclusive with status.")
        ] = False,
    ):
        """Paginated per-recipient results in submission order (zero-based index).

        Filter by **status**, or use **attention=true** to include INVALID and FAILED rows.
        These filters are mutually exclusive. COMPLETED rows have a download_url; other rows do not.
        `total` counts results matching the filter, not the entire batch.
        """
        get_job(db, str(job_id))
        if attention and status:
            raise HTTPException(422, "Choose either status or attention, not both")
        clause = "job_id=?" + (
            " AND status IN ('INVALID','FAILED')"
            if attention
            else " AND status=?"
            if status
            else ""
        )
        params = (str(job_id), status) if status else (str(job_id),)
        with db.connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM recipients WHERE {clause}", params
            ).fetchone()[0]
            rows = connection.execute(
                f"SELECT * FROM recipients WHERE {clause} ORDER BY position LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return RecipientPage(
            items=[recipient_view(row) for row in rows], total=total, limit=limit, offset=offset
        )

    def certificate_response(certificate_id: UUID, inline: bool):
        with db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM recipients WHERE id=?", (str(certificate_id),)
            ).fetchone()
        if row is None:
            raise HTTPException(404, "Certificate not found")
        if row["status"] != "COMPLETED":
            raise HTTPException(409, "Certificate is not available")
        path = db.ensure_pdf(row["job_id"], row["id"])
        if not path.is_file():
            raise HTTPException(410, "Certificate file is missing from storage")
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=f"{row['id']}.pdf",
            content_disposition_type="inline" if inline else "attachment",
        )

    @app.get(
        "/api/certificates/{certificate_id}/download",
        dependencies=secured,
        tags=["Downloads"],
        response_class=FileResponse,
        responses={
            **auth_errors,
            200: {
                "description": "Completed certificate PDF.",
                "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
            },
            404: {"model": APIErrorResponse, "description": "Unknown certificate ID."},
            409: {"model": APIErrorResponse, "description": "Certificate is not completed."},
            410: {
                "model": APIErrorResponse,
                "description": "Generated file is missing from storage.",
            },
        },
    )
    def download_certificate(certificate_id: UUID):
        """Download a completed PDF as an attachment.

        404: unknown ID; 409: not completed; 410: missing stored file.
        """
        return certificate_response(certificate_id, inline=False)

    @app.get(
        "/api/certificates/{certificate_id}/preview",
        dependencies=secured,
        tags=["Certificates"],
        response_class=FileResponse,
        responses={
            **auth_errors,
            200: {
                "description": "Completed PDF with inline Content-Disposition.",
                "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
            },
            404: {"model": APIErrorResponse, "description": "Unknown certificate ID."},
            409: {"model": APIErrorResponse, "description": "Certificate is not completed."},
            410: {
                "model": APIErrorResponse,
                "description": "Generated file is missing from storage.",
            },
        },
    )
    @app.head(
        "/api/certificates/{certificate_id}/preview",
        dependencies=secured,
        include_in_schema=False,
    )
    def preview_certificate(certificate_id: UUID):
        """Return the actual generated PDF inline, not a mockup.

        Uses the same availability rules as download.
        """
        return certificate_response(certificate_id, inline=True)

    @app.get(
        "/api/jobs/{job_id}/download",
        dependencies=secured,
        tags=["Downloads"],
        response_class=FileResponse,
        responses={
            **auth_errors,
            200: {
                "description": "ZIP of successful certificate PDFs.",
                "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
            },
            **unknown_job,
            409: {
                "model": APIErrorResponse,
                "description": "Batch is unfinished or has no successful certificates.",
            },
            410: {"model": APIErrorResponse, "description": "A stored PDF is missing."},
            503: {"model": APIErrorResponse, "description": "Archive build lock timed out; retry."},
        },
    )
    def download_job(job_id: UUID):
        """Download a ZIP containing only successful PDFs, named by certificate UUID.

        Available only after the batch finishes and at least one recipient succeeds (otherwise 409).
        Built lazily on disk and cached; it is not buffered entirely in application memory.
        404: unknown job; 410: missing stored PDF; 503: archive builder is locked, retry shortly.
        """
        try:
            path = build_archive(db, str(job_id))
        except Timeout as exc:
            raise HTTPException(503, "Archive is being built; retry shortly") from exc
        except FileNotFoundError as exc:
            raise HTTPException(410, "A certificate file is missing from storage") from exc
        return FileResponse(path, media_type="application/zip", filename=f"{job_id}.zip")

    return app


app = create_app()
