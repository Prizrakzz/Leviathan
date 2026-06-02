"""Text extraction for FNC Colombia monthly coffee PDF reports."""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

import pdfplumber

from leviathan.transforms.raw_to_text.schema import DocumentJson, Section

SOURCE = "fnc"

_MIN_PAGE_CHARS = 400
_EXPORT_RESUMEN_MIN_CHARS = 250

_MONTHS = {
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "SETIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}
_MONTH_RE = "|".join(_MONTHS)

_PERIOD_PATTERNS = [
    re.compile(rf"PERIODO\s*:\s*(?P<month>{_MONTH_RE})\s+(?P<year>\d{{2,4}})"),
    re.compile(
        rf"INFORME\s+MENSUAL(?:\s+DE\s+EXPORTACIONES)?\s+"
        rf"(?:DE\s+)?(?P<month>{_MONTH_RE})\s+(?P<year>\d{{2,4}})"
    ),
    re.compile(rf"(?P<month>{_MONTH_RE})\s+(?P<year>\d{{4}})"),
]
_FILENAME_PERIOD_RE = re.compile(
    rf"(?:^|[-_\s])(?P<month>{_MONTH_RE})(?:[-_\s]*)(?P<year>\d{{2,4}})(?:[-_.\s]|$)"
)


@dataclass(frozen=True)
class FncTextExtraction:
    """Extracted text document plus routing metadata for the text/ layer."""

    document: DocumentJson
    publication_date: str
    publisher: str


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _normalize_text(value: str) -> str:
    value = _strip_accents(value).upper()
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _parse_year(value: str) -> int:
    year = int(value)
    if year < 100:
        return 2000 + year
    return year


def parse_fnc_publication_date(header_text: str, raw_key: str = "") -> str:
    """Return first day of the report month as ``YYYY-MM-DD``.

    FNC raw keys carry upload dates, not report dates, so the report header is
    the source of truth. Filename parsing is only a fallback for files whose
    header text is unexpectedly sparse.
    """
    normalized = _normalize_text(header_text)
    for pattern in _PERIOD_PATTERNS:
        match = pattern.search(normalized)
        if match:
            month = _MONTHS[match.group("month")]
            year = _parse_year(match.group("year"))
            return f"{year:04d}-{month:02d}-01"

    filename = raw_key.rsplit("/", 1)[-1]
    filename_normalized = _normalize_text(filename)
    match = _FILENAME_PERIOD_RE.search(filename_normalized)
    if match:
        month = _MONTHS[match.group("month")]
        year = _parse_year(match.group("year"))
        return f"{year:04d}-{month:02d}-01"

    raise ValueError(f"Could not parse FNC report publication date from {raw_key}")


def classify_fnc_publisher(header_text: str, report_type: str) -> str:
    """Return the report publisher/layout subtype used for extraction routing."""
    if report_type == "exportaciones":
        return "fnc_exportaciones"
    normalized = _normalize_text(header_text)
    if "FEPCAFE" in normalized or "FONDO DE ESTABILIZACION" in normalized:
        return "fepcafe_reporte_mensual"
    return "fnc_informe_mensual"


def _section_name(index: int, publisher: str) -> str:
    return f"{publisher}_page_{index + 1:02d}"


def _select_page_sections(
    page_texts: list[str],
    report_type: str,
    publisher: str,
) -> list[Section]:
    sections: list[Section] = []
    last_index = len(page_texts) - 1
    for idx, text in enumerate(page_texts):
        clean = text.strip()
        if not clean:
            continue
        if report_type == "exportaciones":
            if idx == 1 and len(clean) >= _EXPORT_RESUMEN_MIN_CHARS:
                sections.append(Section(name="resumen_general", text=clean))
            elif idx > 1 and len(clean) >= 800:
                sections.append(Section(name=_section_name(idx, publisher), text=clean))
            continue

        if publisher == "fepcafe_reporte_mensual":
            if idx == 0 or idx == last_index:
                continue
            if len(clean) >= _MIN_PAGE_CHARS:
                sections.append(Section(name=_section_name(idx, publisher), text=clean))
            continue

        if idx == 0:
            continue
        if len(clean) >= _MIN_PAGE_CHARS:
            sections.append(Section(name=_section_name(idx, publisher), text=clean))

    return sections


def extract_fnc_pdf(
    pdf_bytes: bytes,
    raw_key: str,
    report_type: str,
) -> FncTextExtraction:
    """Extract GraphRAG-ready narrative text from one FNC monthly report PDF."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page_texts = [page.extract_text() or "" for page in pdf.pages]

    header_text = "\n".join(page_texts[:2])
    publication_date = parse_fnc_publication_date(header_text, raw_key)
    publisher = classify_fnc_publisher(header_text, report_type)
    sections = _select_page_sections(page_texts, report_type, publisher)
    full_text = "\n\n".join(section["text"] for section in sections).strip()

    if not full_text:
        full_text = "\n\n".join(text.strip() for text in page_texts if text.strip()).strip()
        sections = [Section(name="full", text=full_text)] if full_text else []

    document = DocumentJson(
        source=SOURCE,
        raw_key=raw_key,
        extraction_method="pdfplumber",
        extracted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sections=sections,
        full_text=full_text,
    )
    return FncTextExtraction(
        document=document,
        publication_date=publication_date,
        publisher=publisher,
    )
