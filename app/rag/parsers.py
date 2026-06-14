"""Extract plain text from uploaded knowledge-base files (PDF/DOCX/TXT)."""

from __future__ import annotations

import io
from pathlib import Path


class UnsupportedFileType(ValueError):
    """Raised when a file extension has no parser."""


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_docx(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


def _extract_txt(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


_PARSERS = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".txt": _extract_txt,
    ".md": _extract_txt,
}


def supported_extensions() -> tuple[str, ...]:
    return tuple(_PARSERS)


def extract_text(filename: str, data: bytes) -> str:
    """Return text extracted from ``data``, dispatching by file extension."""
    ext = Path(filename).suffix.lower()
    parser = _PARSERS.get(ext)
    if parser is None:
        raise UnsupportedFileType(
            f"Unsupported file type {ext!r}; supported: "
            f"{', '.join(supported_extensions())}"
        )
    return parser(data).strip()
