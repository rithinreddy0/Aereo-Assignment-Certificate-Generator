"""Shared settings: the API and worker must use the same data directory."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    max_recipients: int = 10_000
    max_body_bytes: int = 8 * 1024 * 1024
    poll_seconds: float = 1.0
    api_key: str = ""
    database_url: str = ""
    embedded_worker: bool = False

    def __post_init__(self):
        if self.max_recipients < 1 or self.max_body_bytes < 1 or self.poll_seconds <= 0:
            raise ValueError("Limits and polling interval must be positive")

    @classmethod
    def from_env(cls):
        return cls(
            data_dir=Path(os.getenv("CERT_DATA_DIR", "data")).resolve(),
            max_recipients=int(os.getenv("CERT_MAX_RECIPIENTS", "10000")),
            max_body_bytes=int(os.getenv("CERT_MAX_BODY_BYTES", str(8 * 1024 * 1024))),
            poll_seconds=float(os.getenv("CERT_POLL_SECONDS", "1")),
            api_key=os.getenv("CERT_API_KEY", ""),
            database_url=os.getenv("DATABASE_URL", ""),
            embedded_worker=os.getenv("CERT_EMBEDDED_WORKER", "false").lower() == "true",
        )
