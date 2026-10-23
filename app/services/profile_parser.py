"""Conservative local extraction: each non-heading line is retained as an exact sourced fact."""
import json
import re
import subprocess
import sys
from uuid import UUID, uuid5

from app.core.config import ROOT
from app.core.errors import DomainError
from app.schemas.ai import ProfileDraft, SourcedFact, SourceSpan

SECTIONS = {
    "skills": ("skills", "technical skills", "technologies", "technical expertise"),
    "education": ("education", "academic background", "qualifications"),
    "experience": ("experience", "work experience", "professional experience", "internships", "employment"),
    "projects": ("projects", "personal projects", "academic projects", "selected projects"),
    "certifications": ("certifications", "certificates"),
    "achievements": ("achievements", "awards", "honors", "honours"),
    "summary": ("summary", "profile", "objective", "professional summary"),
}


def extract_pdf(content: bytes, *, max_pages=10):
    if len(content) > 5 * 1024 * 1024:
        raise DomainError("PDF_TOO_LARGE", "PDFs must be no larger than 5 MiB.", 413)
    if not content.startswith(b"%PDF-"):
        raise DomainError("UNREADABLE_PDF", "Choose a valid text-based PDF.", 415)
    try:
        from app.services.pdf_render import isolated
        output = isolated("app.tools.pdf_extract",content,20,args=(str(max_pages),))
        if len(output) > 600000:
            raise DomainError("PDF_RESOURCE_LIMIT", "The PDF exceeded safe processing limits.", 422)
        payload = json.loads(output)
    except subprocess.TimeoutExpired:
        raise DomainError("PDF_PROCESSING_TIMEOUT", "The PDF exceeded the parsing time limit.", 422) from None
    except (ValueError, OSError):
        raise DomainError("UNREADABLE_PDF", "The PDF could not be read safely.", 422) from None
    if payload.get("error"):
        code = payload["error"]
        raise DomainError(code, "The PDF needs correction: use an unencrypted text-based PDF, at most 10 pages and 5 MiB. OCR is not applied.", 422)
    return payload["pages"]


def verify_span(pages, source):
    source = SourceSpan.model_validate(source) if isinstance(source, dict) else source
    page = next((page for page in pages if page["page"] == source.page), None)
    return bool(page and page["text"][source.start_offset:source.end_offset] == source.source_text)


def parse_profile(pages, namespace: UUID) -> ProfileDraft:
    facts, section, first_line = [], "other", True
    for page in pages:
        offset = 0
        for raw in page["text"].splitlines(keepends=True):
            text = raw.strip()
            start = offset + len(raw) - len(raw.lstrip())
            offset += len(raw)
            if not text:
                continue
            key = text.casefold().strip(": ")
            heading = next((kind for kind, labels in SECTIONS.items() if key in labels), None)
            if heading:
                section = heading
                continue
            inline = next(((kind, label) for kind, labels in SECTIONS.items() for label in labels
                           if key.startswith(label + ":")), None)
            if inline:
                section, label = inline
                prefix = text.index(":") + 1
                rest = text[prefix:]
                start += prefix + len(rest) - len(rest.lstrip())
                text = rest.strip()
                if not text:
                    continue
            kind = section
            if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text):
                kind = "email"
            elif section == "other" and re.search(r"(?:https?://|www\.|linkedin\.com|github\.com)", text, re.I):
                kind = "links"
            elif section == "other" and re.fullmatch(r"[+\d ()-]{7,25}", text):
                kind = "phone"
            elif first_line and len(text.split()) in range(2, 6) and not re.search(r"\d|[@/:]", text):
                kind = "name"
            first_line = False
            source = SourceSpan(page=page["page"], start_offset=start, end_offset=start + len(text), source_text=text)
            if not verify_span(pages, source):
                raise DomainError("SOURCE_SPAN_INVALID", "Extracted source evidence did not validate.", 422)
            facts.append(SourcedFact(id=uuid5(namespace, f"{page['page']}:{start}:{kind}"), kind=kind,
                                    value=text, source_ref=source))
    if not facts or len(facts) > 200 or any(len(str(f.value)) > 4000 for f in facts):
        raise DomainError("PROFILE_TEXT_LIMIT", "This resume needs manual shortening before safe review.", 422)
    by_kind = lambda kind: [str(f.value) for f in facts if f.kind == kind]
    contact = {kind: next(iter(by_kind(kind)), None) for kind in ("name", "email", "phone", "links")}
    warnings = ["Local extraction preserves individual source lines. Review wrapped bullets, section assignments and contact fields before confirming."]
    warnings += [f"{kind.capitalize()} not identified; add it explicitly if appropriate." for kind in ("name", "email") if not contact[kind]]
    return ProfileDraft(contact=contact, education=by_kind("education"), skills=by_kind("skills"),
        projects=by_kind("projects"), experience=by_kind("experience"),
        other_sections={kind: by_kind(kind) for kind in ("summary", "certifications", "achievements", "other") if by_kind(kind)},
        facts=facts, warnings=warnings)
