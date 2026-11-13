import pytest

from resume_matcher.errors import (
    CorruptedDocumentError,
    DocumentError,
    EmptyDocumentError,
    UnsupportedFormatError,
)
from resume_matcher.parsing import extract_text


def test_txt(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("Jane Doe\nPython developer with experience in building APIs and services.", encoding="utf-8")
    assert "Python developer" in extract_text(p)


def test_docx_with_table(tmp_path):
    import docx

    d = docx.Document()
    d.add_paragraph("Jane Doe - Senior Engineer with a long history of building software")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text = "Skills"
    t.rows[0].cells[1].text = "Python, Docker, Kubernetes"
    p = tmp_path / "r.docx"
    d.save(p)
    text = extract_text(p)
    assert "Senior Engineer" in text and "Kubernetes" in text


def test_docx_header_text_is_read_and_missing_header_is_not_created(tmp_path):
    import docx

    plain = docx.Document()
    plain.add_paragraph("Plain resume body text that is long enough to be accepted.")
    p1 = tmp_path / "plain.docx"
    plain.save(p1)
    assert "Plain resume body" in extract_text(p1)

    with_header = docx.Document()
    with_header.sections[0].header.paragraphs[0].text = "Jane Doe | jane@example.com"
    with_header.add_paragraph("Body of a resume that has a page header with the contact details.")
    p2 = tmp_path / "hdr.docx"
    with_header.save(p2)
    text = extract_text(p2)
    assert "Jane Doe | jane@example.com" in text and text.count("Jane Doe") == 1


def test_pdf(tmp_path):
    from reportlab.pdfgen import canvas

    p = tmp_path / "r.pdf"
    c = canvas.Canvas(str(p))
    c.drawString(72, 750, "Jane Doe - Data Scientist with strong Python and SQL skills")
    c.save()
    assert "Data Scientist" in extract_text(p)


def test_unsupported(tmp_path):
    p = tmp_path / "r.exe"
    p.write_bytes(b"MZ")
    with pytest.raises(UnsupportedFormatError):
        extract_text(p)


def test_empty_file(tmp_path):
    p = tmp_path / "e.pdf"
    p.write_bytes(b"")
    with pytest.raises(EmptyDocumentError):
        extract_text(p)


def test_corrupted_pdf(tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"%PDF-1.4 this is not really a pdf at all" * 5)
    with pytest.raises(CorruptedDocumentError):
        extract_text(p)


def test_fake_pdf_extension(tmp_path):
    p = tmp_path / "fake.pdf"
    p.write_bytes(b"hello world, definitely not a pdf" * 5)
    with pytest.raises(CorruptedDocumentError):
        extract_text(p)


def test_corrupted_docx(tmp_path):
    p = tmp_path / "bad.docx"
    p.write_bytes(b"not a zip file" * 10)
    with pytest.raises(CorruptedDocumentError):
        extract_text(p)


def test_missing_file(tmp_path):
    with pytest.raises(DocumentError):
        extract_text(tmp_path / "nope.pdf")


def test_blank_text_pdf_reports_empty(tmp_path):
    from reportlab.pdfgen import canvas

    p = tmp_path / "blank.pdf"
    c = canvas.Canvas(str(p))
    c.showPage()
    c.save()
    with pytest.raises(EmptyDocumentError):
        extract_text(p)
