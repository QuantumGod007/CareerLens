"""Synthetic HTML -> Chromium PDF -> page-specific text; no AI rewriting."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pdfplumber
from jinja2 import Environment, StrictUndefined
from pypdf import PdfReader, PdfWriter

from scripts.feasibility.common import OUTPUT, ProbeError, browser_environment, emit, failed

MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 10
TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><style>
@page {size:A4; margin:18mm}
body {font-family:Arial,sans-serif; font-size:11pt; line-height:1.45; color:#111}
h1 {font-size:22pt; margin:0 0 6pt} h2 {font-size:13pt; margin:18pt 0 6pt}
p {margin:5pt 0} li {margin:5pt 0} .next {break-before:page}
</style></head><body>
<h1>{{ name }}</h1><p>{{ email }}</p><p>SYNTHETIC FIXTURE - NOT A REAL APPLICANT</p>
<h2>Skills</h2><p>Python, FastAPI, SQL, Git</p>
<h2>Projects</h2><ul><li>Built a synthetic task API using FastAPI and SQL.</li>
<li>{{ project }}</li></ul><p>Résumé - café - naïve - • Unicode extraction check</p>
<p>PAGE_ONE_MARKER</p>
<section class="next"><h2>Education</h2><p>Synthetic University, 2024-2026</p>
<p>This second page validates page-specific extraction.</p><p>PAGE_TWO_MARKER</p></section>
</body></html>"""


def read_pdf(path: Path) -> list[dict]:
    if path.stat().st_size > MAX_BYTES:
        raise ProbeError("PDF_TOO_LARGE")
    with path.open("rb") as stream:
        if not stream.read(8).startswith(b"%PDF-"):
            raise ProbeError("UNREADABLE_PDF")
    try:
        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise ProbeError("ENCRYPTED_PDF")
        if not reader.pages:
            raise ProbeError("EMPTY_PDF")
        if len(reader.pages) > MAX_PAGES:
            raise ProbeError("TOO_MANY_PAGES")
        with pdfplumber.open(path) as document:
            pages = []
            for number, page in enumerate(document.pages, start=1):
                text = page.extract_text() or ""
                pages.append({"page": number, "text": text, "start_offset": 0, "end_offset": len(text)})
        if not any(page["text"].strip() for page in pages):
            raise ProbeError("NO_EXTRACTABLE_TEXT")
        return pages
    except ProbeError:
        raise
    except Exception as error:
        raise ProbeError("UNREADABLE_PDF") from error


def render_synthetic_pdf(path: Path) -> dict:
    from playwright.sync_api import sync_playwright

    browser_environment()
    environment = Environment(autoescape=True, undefined=StrictUndefined)
    html = environment.from_string(TEMPLATE).render(
        name="Synthetic Candidate", email="candidate@example.invalid",
        project="R&D <testing> & SQL - no unsupported achievements",
    )
    with sync_playwright() as playwright:
        with playwright.chromium.launch() as browser:
            context = browser.new_context(java_script_enabled=False)
            context.route("**/*", lambda route: route.abort())
            page = context.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(path=str(path), print_background=True, prefer_css_page_size=True)
            context.close()
    pages = read_pdf(path)
    text = unicodedata.normalize("NFC", "\n".join(page["text"] for page in pages))
    expected = ["Synthetic Candidate", "candidate@example.invalid", "FastAPI", "SQL",
                "R&D <testing> & SQL", "Résumé", "café", "naïve", "2024-2026"]
    missing = [value for value in expected if value not in text]
    if missing or len(pages) != 2:
        raise ProbeError("PDF_ROUNDTRIP_MISMATCH")
    if "PAGE_ONE_MARKER" not in pages[0]["text"] or "PAGE_TWO_MARKER" not in pages[1]["text"]:
        raise ProbeError("PDF_PAGE_MAPPING_FAILED")
    return {"pages": pages, "retained_values": expected, "unicode_roundtrip": "PASS",
            "html_escaping": "PASS", "scripts_disabled": True, "network_disabled": True}


def create_negative_fixtures(directory: Path, source: Path) -> dict[str, tuple[Path, str]]:
    fixtures = {}
    for name, count, code in [("empty", 0, "EMPTY_PDF"), ("blank", 1, "NO_EXTRACTABLE_TEXT"),
                              ("too-many-pages", 11, "TOO_MANY_PAGES")]:
        writer = PdfWriter()
        for _ in range(count):
            writer.add_blank_page(width=595, height=842)
        target = directory / f"{name}.pdf"
        writer.write(target)
        fixtures[name] = (target, code)
    encrypted = directory / "encrypted.pdf"
    writer = PdfWriter(clone_from=source)
    writer.encrypt("synthetic-test-password")
    writer.write(encrypted)
    fixtures["encrypted"] = (encrypted, "ENCRYPTED_PDF")
    malformed = directory / "malformed.pdf"
    malformed.write_bytes(b"This is not a PDF")
    fixtures["malformed"] = (malformed, "UNREADABLE_PDF")
    truncated = directory / "truncated.pdf"
    truncated.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n")
    fixtures["truncated"] = (truncated, "UNREADABLE_PDF")
    oversized = directory / "oversized.pdf"
    with oversized.open("wb") as stream:
        stream.write(b"%PDF-1.7\n")
        stream.truncate(MAX_BYTES + 1)
    fixtures["oversized"] = (oversized, "PDF_TOO_LARGE")
    return fixtures


def run() -> dict:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source = OUTPUT / "synthetic-resume.pdf"
    result = render_synthetic_pdf(source)
    rejected = {}
    for name, (path, expected) in create_negative_fixtures(OUTPUT, source).items():
        try:
            read_pdf(path)
        except ProbeError as error:
            assert error.code == expected
            rejected[name] = error.code
        else:
            raise AssertionError(f"Accepted invalid fixture {name}")
    return {"status": "PASS", "synthetic_data_only": True, **result,
            "negative_fixtures": rejected, "max_bytes": MAX_BYTES, "max_pages": MAX_PAGES,
            "limitations": ["OCR not implemented", "Common Latin Unicode tested; other scripts not assessed",
                             "No universal ATS certification or arbitrary-PDF layout validation"]}


if __name__ == "__main__":
    try:
        emit("pdf", run())
    except Exception as error:
        raise SystemExit(failed("pdf", error))
