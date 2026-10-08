"""Envelope errors reject requests; recipient errors are recorded per recipient."""

import unicodedata
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.templates import TemplateId

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


def clean_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("Control and invisible formatting characters are not allowed")
    return value


class CertificateInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    organization: Text = Field(description="Issuing organization, printed on every certificate.")
    course: Text = Field(description="Course or event being recognized.")
    title: Text = Field(
        default="Certificate of Completion", description="Main certificate heading."
    )
    issued_on: date = Field(description="Actual calendar date, formatted YYYY-MM-DD.")
    signatory: Text = Field(description="Name of the person issuing the certificate.")
    signatory_role: Text = Field(default="Program Director", description="Printed signatory role.")
    template: TemplateId = Field(
        default="classic",
        description="Preset design for this batch. Discover IDs at GET /api/templates.",
    )

    @field_validator("issued_on", mode="before")
    @classmethod
    def parse_date(cls, value):
        # A JSON date is a string; do not accept numeric timestamps or datetimes.
        if isinstance(value, str):
            return date.fromisoformat(value)
        if type(value) is date:
            return value
        raise ValueError("Use a date in YYYY-MM-DD format")

    @field_validator("organization", "course", "title", "signatory", "signatory_role")
    @classmethod
    def text_is_printable(cls, value):
        return clean_text(value)


class Recipient(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: Text
    email: EmailStr | None = None
    reference: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None

    @field_validator("name", "reference")
    @classmethod
    def text_is_printable(cls, value):
        return clean_text(value) if value is not None else None


class JobCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "examples": [
                {
                    "certificate": {
                        "template": "modern",
                        "organization": "Aereo Academy",
                        "course": "Python Backend Development",
                        "issued_on": "2026-10-08",
                        "signatory": "Vidya Pawar",
                        "signatory_role": "Program Director",
                    },
                    "recipients": [
                        {
                            "name": "Alex Morgan",
                            "email": "alex@example.com",
                            "reference": "STUDENT-001",
                        },
                        {"name": "Renée Müller", "email": "renee@example.com"},
                    ],
                }
            ],
        },
    )
    certificate: CertificateInfo
    # Deliberately validated individually: a malformed row must not reject valid rows.
    recipients: list[Any] = Field(
        min_length=1,
        max_length=100_000,
        description="Objects: name (1–120 chars), optional email and reference (max 80 chars). "
        "Each row is validated independently; invalid rows do not reject valid ones. "
        "The configured default limit is 10,000 recipients and 8 MiB per request.",
    )


JobStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"]
RecipientStatus = Literal["QUEUED", "PROCESSING", "COMPLETED", "INVALID", "FAILED"]


class JobView(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "7401d4c6-9929-45cf-9e42-7cadb4888239",
                    "status": "QUEUED",
                    "total": 2,
                    "succeeded": 0,
                    "failed": 0,
                    "invalid": 0,
                    "pending": 2,
                    "progress_percent": 0,
                    "created_at": "2026-10-08T09:00:00+00:00",
                    "finished_at": None,
                    "certificate": {
                        "organization": "Aereo Academy",
                        "course": "Python Backend Development",
                        "title": "Certificate of Completion",
                        "issued_on": "2026-10-08",
                        "signatory": "Vidya Pawar",
                        "signatory_role": "Program Director",
                        "template": "modern",
                    },
                }
            ]
        }
    )
    id: str
    status: JobStatus
    total: int
    succeeded: int
    failed: int = Field(description="All unsuccessful rows, including invalid input rows.")
    invalid: int = Field(
        description="Input validation failures; a subset of failed, not additional."
    )
    pending: int = Field(
        description="Rows awaiting an outcome: total minus succeeded minus failed."
    )
    progress_percent: float = Field(
        description="Processed outcomes, including failures; 100 is not all-success."
    )
    created_at: str
    finished_at: str | None
    certificate: CertificateInfo


class JobPage(BaseModel):
    items: list[JobView]
    total: int
    limit: int
    offset: int


class RecipientView(BaseModel):
    id: str
    index: int
    name: str | None
    email: str | None
    reference: str | None
    status: RecipientStatus
    error: str | None
    download_url: str | None


class RecipientPage(BaseModel):
    items: list[RecipientView]
    total: int
    limit: int
    offset: int
