import pytest
from pypdf import PdfWriter

from scripts.feasibility.common import ProbeError
from scripts.feasibility.test_pdf_pipeline import read_pdf


@pytest.mark.parametrize("page_count,code", [(0, "EMPTY_PDF"), (1, "NO_EXTRACTABLE_TEXT"),
                                          (11, "TOO_MANY_PAGES")])
def test_empty_blank_and_page_limit(tmp_path, page_count, code):
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=595, height=842)
    path = tmp_path / "synthetic.pdf"
    writer.write(path)
    with pytest.raises(ProbeError, match=code):
        read_pdf(path)


def test_malformed_pdf(tmp_path):
    path = tmp_path / "malformed.pdf"
    path.write_bytes(b"not pdf")
    with pytest.raises(ProbeError, match="UNREADABLE_PDF"):
        read_pdf(path)


def test_truncated_pdf_with_valid_header(tmp_path):
    path = tmp_path / "truncated.pdf"
    path.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n")
    with pytest.raises(ProbeError, match="UNREADABLE_PDF"):
        read_pdf(path)


def test_encrypted_pdf(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.encrypt("synthetic")
    path = tmp_path / "encrypted.pdf"
    writer.write(path)
    with pytest.raises(ProbeError, match="ENCRYPTED_PDF"):
        read_pdf(path)


def test_actual_size_limit(tmp_path):
    path = tmp_path / "too-large.pdf"
    with path.open("wb") as stream:
        stream.truncate(5 * 1024 * 1024 + 1)
    with pytest.raises(ProbeError, match="PDF_TOO_LARGE"):
        read_pdf(path)
