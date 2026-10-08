"""Three vector PDF presets sharing bounded text fitting and atomic output."""

from functools import lru_cache
from pathlib import Path

import reportlab
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from app.schemas import CertificateInfo

REGULAR = "CertificateSans"
BOLD = "CertificateSansBold"
NAVY = HexColor("#102B3F")
GOLD = HexColor("#B18B43")
GRAY = HexColor("#52616A")


def register_fonts():
    if REGULAR not in pdfmetrics.getRegisteredFontNames():
        fonts = Path(reportlab.__file__).parent / "fonts"
        pdfmetrics.registerFont(TTFont(REGULAR, str(fonts / "Vera.ttf")))
        pdfmetrics.registerFont(TTFont(BOLD, str(fonts / "VeraBd.ttf")))


def validate_text(text: str):
    register_fonts()
    for font in (REGULAR, BOLD):
        glyphs = pdfmetrics.getFont(font).face.charToGlyph
        if any(ord(char) not in glyphs for char in text):
            raise ValueError("Text contains characters unsupported by the certificate font")


def validate_template_text(info: CertificateInfo):
    for field in (info.organization, info.course, info.title, info.signatory, info.signatory_role):
        validate_text(field)


@lru_cache(maxsize=256)
def wrap_text(text: str, font: str, size: float, width: float) -> tuple[str, ...]:
    """Wrap at spaces, splitting long tokens rather than letting them cross the border."""
    lines: list[str] = []
    current = ""
    current_width = 0.0
    char_widths: dict[str, float] = {}
    for char in text:
        if char not in char_widths:
            char_widths[char] = pdfmetrics.stringWidth(char, font, size)
        char_width = char_widths[char]
        if current_width + char_width > width:
            split = current.rfind(" ")
            if split > 0:
                lines.append(current[:split])
                current = current[split + 1 :] + char
            else:
                lines.append(current)
                current = char
            current_width = pdfmetrics.stringWidth(current, font, size)
        else:
            current += char
            current_width += char_width
    if current:
        lines.append(current.strip())
    return tuple(lines)


def centered(
    canvas: Canvas,
    text: str,
    y: float,
    size: float,
    font: str = REGULAR,
    width: float = 700,
    max_lines: int = 2,
    color=NAVY,
):
    while True:
        lines = wrap_text(text, font, size, width)
        if len(lines) <= max_lines:
            break
        size -= 1
        if size < 10:
            raise ValueError("Text is too long to fit in this template")
    canvas.setFillColor(color)
    canvas.setFont(font, size)
    for index, line in enumerate(lines):
        canvas.drawCentredString(landscape(A4)[0] / 2, y - index * size * 1.2, line)


def render_certificate(
    path: Path, info: CertificateInfo, name: str, certificate_id: str, reference: str | None = None
):
    """Write atomically: a completed DB row can only reference a complete PDF."""
    validate_template_text(info)
    validate_text(name)
    if reference:
        validate_text(reference)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".pdf.tmp")
    try:
        width, height = landscape(A4)
        canvas = Canvas(str(temporary), pagesize=(width, height), pageCompression=1)
        canvas.setTitle(f"{info.title} - {name}")
        canvas.setAuthor(info.organization)
        modern = info.template == "modern"
        minimal = info.template == "minimal"
        ink = HexColor("#303B36") if minimal else NAVY
        muted = HexColor("#656D68") if minimal else GRAY
        accent = HexColor("#16877B") if modern else ink if minimal else GOLD
        canvas.setFillColor(HexColor("#FFFFFF" if minimal or modern else "#FCFAF5"))
        canvas.rect(0, 0, width, height, fill=1, stroke=0)
        if modern:
            canvas.setFillColor(NAVY)
            canvas.rect(0, 490, width, height - 490, fill=1, stroke=0)
            canvas.setFillColor(accent)
            canvas.rect(0, 0, 14, height, fill=1, stroke=0)
            canvas.rect(14, 0, width - 14, 18, fill=1, stroke=0)
        elif minimal:
            canvas.setStrokeColor(HexColor("#CFD5D0"))
            canvas.setLineWidth(0.6)
            canvas.rect(35, 35, width - 70, height - 70)
            canvas.setStrokeColor(ink)
            canvas.line(70, 478, 270, 478)
            canvas.line(width - 270, 478, width - 70, 478)
        else:
            canvas.setStrokeColor(GOLD)
            canvas.setLineWidth(1.2)
            canvas.rect(26, 26, width - 52, height - 52)
            canvas.setStrokeColor(HexColor("#DED6C6"))
            canvas.setLineWidth(0.4)
            canvas.rect(33, 33, width - 66, height - 66)
        centered(
            canvas,
            info.organization,
            520,
            15,
            BOLD,
            max_lines=2,
            color=HexColor("#FFFFFF") if modern else ink,
        )
        canvas.setStrokeColor(accent)
        canvas.line(width / 2 - 25, 478, width / 2 + 25, 478)
        centered(canvas, info.title, 436, 31, BOLD, max_lines=2, color=ink)
        centered(canvas, "THIS CERTIFICATE IS PROUDLY PRESENTED TO", 350, 10, color=muted)
        centered(canvas, name, 305, 36, BOLD, max_lines=2, color=accent if modern else ink)
        centered(canvas, "for successfully completing", 230, 12, color=muted)
        centered(canvas, info.course, 204, 20, BOLD, max_lines=2, color=ink)
        centered(canvas, f"Issued on {info.issued_on.strftime('%d %B %Y')}", 142, 11, color=muted)
        centered(canvas, info.signatory, 108, 13, BOLD, max_lines=2, color=ink)
        centered(canvas, info.signatory_role, 73, 10, max_lines=2, color=muted)
        footer = f"Certificate ID: {certificate_id}"
        if reference:
            footer += f"  |  Reference: {reference}"
        centered(canvas, footer, 48, 8, width=width - 100, max_lines=2, color=muted)
        canvas.showPage()
        canvas.save()
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
