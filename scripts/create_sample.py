"""Create a sample certificate for visual inspection; no database required."""

import argparse
import json
from pathlib import Path

from app.renderer import render_certificate
from app.schemas import CertificateInfo, JobCreate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stress", action="store_true", help="Render maximum-length text for QA")
    parser.add_argument("--template", choices=("classic", "modern", "minimal"), default="classic")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    payload = JobCreate.model_validate_json((root / "examples" / "job.json").read_text())
    info = payload.certificate
    info.template = args.template
    output = root / "output" / "pdf" / f"sample-{args.template}.pdf"
    name = payload.recipients[0]["name"]
    reference = "STUDENT-001"
    if args.stress:
        output = root / "tmp" / "pdfs" / f"stress-{args.template}.pdf"
        info = CertificateInfo(
            organization="W" * 120,
            course="W" * 120,
            title="W" * 120,
            issued_on="2026-10-08",
            signatory="W" * 120,
            signatory_role="W" * 120,
            template=args.template,
        )
        name, reference = "W" * 120, "W" * 80
    render_certificate(
        output,
        info,
        name,
        "7401d4c6-9929-45cf-9e42-7cadb4888239",
        reference,
    )
    print(json.dumps({"sample_pdf": str(output)}))


if __name__ == "__main__":
    main()
