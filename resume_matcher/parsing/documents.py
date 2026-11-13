"""Text extraction from PDF, DOCX and plain-text files."""

from __future__ import annotations

import hashlib
import logging
import re
import zipfile
from pathlib import Path

from ..errors import (
    CorruptedDocumentError,
    DocumentError,
    EmptyDocumentError,
    UnsupportedFormatError,
)

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")
MAX_FILE_BYTES = 15 * 1024 * 1024
MIN_TEXT_CHARS = 40


def file_sha256(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _clean(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _read_pdf(path: Path) -> str:
    try:
        import pymupdf  # PyMuPDF >= 1.24 exposes "pymupdf"
    except ImportError:  # older releases
        import fitz as pymupdf  # type: ignore

    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise CorruptedDocumentError(
            f"'{path.name}' could not be opened. The PDF appears to be damaged."
        ) from exc
    try:
        if doc.needs_pass:
            raise DocumentError(f"'{path.name}' is password-protected. Remove the password and try again.")
        parts = []
        for page in doc:
            parts.append(page.get_text("text", sort=True))
        return "\n".join(parts)
    except DocumentError:
        raise
    except Exception as exc:
        raise CorruptedDocumentError(f"'{path.name}' could not be read: the PDF appears to be damaged.") from exc
    finally:
        doc.close()


def _read_docx(path: Path) -> str:
    import docx  # python-docx

    if not zipfile.is_zipfile(path):
        raise CorruptedDocumentError(f"'{path.name}' is not a valid DOCX file.")
    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise CorruptedDocumentError(f"'{path.name}' could not be opened. The DOCX appears to be damaged.") from exc

    lines: list[str] = []
    seen_headers: set[str] = set()
    for section in document.sections:
        header = section.header
        # Accessing a header that does not exist would make python-docx create one.
        if header.is_linked_to_previous:
            continue
        for p in header.paragraphs:
            t = p.text.strip()
            if t and t not in seen_headers:
                seen_headers.add(t)
                lines.append(p.text)
    for p in document.paragraphs:
        lines.append(p.text)
    for table in document.tables:  # many resumes use tables for layout
        for row in table.rows:
            seen = set()
            cells = []
            for cell in row.cells:
                if id(cell._tc) in seen:  # merged cells repeat
                    continue
                seen.add(id(cell._tc))
                if cell.text.strip():
                    cells.append(cell.text.strip())
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    raise CorruptedDocumentError(f"'{path.name}' is not readable text.")


def extract_text(path: Path | str) -> str:
    """Return cleaned text from a supported document or raise a DocumentError."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"'{path.name}' is not supported. Please use PDF or DOCX "
            f"(text files are also accepted for job descriptions)."
        )
    try:
        size = path.stat().st_size
    except FileNotFoundError as exc:
        raise DocumentError(f"'{path.name}' was not found.") from exc
    except PermissionError as exc:
        raise DocumentError(f"'{path.name}' cannot be read: permission denied.") from exc
    if size == 0:
        raise EmptyDocumentError(f"'{path.name}' is empty.")
    if size > MAX_FILE_BYTES:
        raise DocumentError(f"'{path.name}' is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")

    try:
        if ext == ".pdf":
            with open(path, "rb") as fh:
                if not fh.read(5).startswith(b"%PDF"):
                    raise CorruptedDocumentError(f"'{path.name}' is not a valid PDF file.")
            text = _read_pdf(path)
        elif ext == ".docx":
            text = _read_docx(path)
        else:
            text = _read_text(path)
    except PermissionError as exc:
        raise DocumentError(f"'{path.name}' cannot be read: permission denied.") from exc
    except OSError as exc:
        raise DocumentError(f"'{path.name}' could not be read ({exc.strerror or 'I/O error'}).") from exc

    text = _clean(text)
    if len(text) < MIN_TEXT_CHARS:
        hint = " It may be a scanned image; OCR is not supported yet." if ext == ".pdf" else ""
        raise EmptyDocumentError(f"No readable text was found in '{path.name}'.{hint}")
    return text
