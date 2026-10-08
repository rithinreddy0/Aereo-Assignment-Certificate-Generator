from io import BytesIO

import pytest
from pypdf import PdfReader

from app.renderer import render_certificate
from app.schemas import CertificateInfo


@pytest.mark.parametrize("template", ["classic", "modern", "minimal"])
def test_long_fields_still_produce_one_page(tmp_path, template):
    info = CertificateInfo(
        organization="Organization " * 9,
        course="Advanced Training " * 6,
        title="Certificate " * 9,
        issued_on="2026-10-08",
        signatory="W" * 120,
        signatory_role="Role " * 20,
        template=template,
    )
    path = tmp_path / "long.pdf"
    render_certificate(path, info, "W" * 120, "test-certificate", "REF" * 26)
    assert len(PdfReader(BytesIO(path.read_bytes())).pages) == 1
    assert not path.with_suffix(".pdf.tmp").exists()
