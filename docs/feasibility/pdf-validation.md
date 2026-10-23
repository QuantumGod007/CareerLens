# PDF validation

Executed 23 October 2026, India Standard Time. Status: PASS for synthetic two-page rendering/extraction and negative fixtures.

Jinja2 generated escaped HTML with synthetic identity, skills, projects and education. Chromium rendered it with scripts and network access disabled. pdfplumber extracted each page with page number and exact text offsets. No AI rewriting occurred.

The round trip retained synthetic name/email, skills, education dates, literal `R&D <testing> & SQL` and common Latin Unicode (`Résumé`, `café`, `naïve`). Page markers appeared on the correct pages. Both rendered pages were visually inspected; no clipping, overlaps or missing tested characters were observed. This is a feasibility fixture, not the final resume template.

| Fixture | Rejection code |
| --- | --- |
| Zero-page PDF | EMPTY_PDF |
| Blank page | NO_EXTRACTABLE_TEXT |
| Non-PDF bytes | UNREADABLE_PDF |
| Truncated PDF with valid header | UNREADABLE_PDF |
| Encrypted PDF | ENCRYPTED_PDF |
| Eleven-page PDF | TOO_MANY_PAGES |
| Over 5 MiB | PDF_TOO_LARGE |

Limits are ten pages and 5 MiB (5,242,880 bytes). Full upload/MIME validation, source provenance mapping, long real resumes, broad Unicode/accessibility and OCR remain later work. The no-text fixture is blank; an actual scanned/image-only resume was not separately tested. No universal ATS compatibility is claimed.

Reproduce: `.venv/bin/python -m scripts.feasibility.test_pdf_pipeline`. Local evidence: `data/feasibility/pdf.json`, synthetic PDFs and page preview PNGs. Fixtures and screenshots are ignored by Git.
