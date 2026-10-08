"""Public, fixed template catalogue. No user-supplied HTML or executable templates."""

from typing import Literal

from pydantic import BaseModel

TemplateId = Literal["classic", "modern", "minimal"]


class TemplateView(BaseModel):
    id: TemplateId
    name: str
    description: str
    accent_color: str
    page_format: str = "A4 landscape"


class TemplateCatalogue(BaseModel):
    default: TemplateId = "classic"
    items: list[TemplateView]


TEMPLATES = (
    TemplateView(
        id="classic",
        name="Classic",
        accent_color="#B18B43",
        description="Warm ivory, a double gold border, and timeless formal typography.",
    ),
    TemplateView(
        id="modern",
        name="Modern",
        accent_color="#16877B",
        description="A navy masthead and teal accents for courses and contemporary events.",
    ),
    TemplateView(
        id="minimal",
        name="Minimal",
        accent_color="#303B36",
        description="Clean white space, fine charcoal lines, and understated typography.",
    ),
)
