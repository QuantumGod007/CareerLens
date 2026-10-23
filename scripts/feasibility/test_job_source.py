"""A single configured Lever board; no arbitrary-URL crawler or hidden fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from scripts.feasibility.common import ProbeError, emit, failed, now

BOARD = "drivetrain"
ENDPOINT = f"https://api.lever.co/v0/postings/{BOARD}?mode=json"
MAX_RESPONSE = 3 * 1024 * 1024


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_id: str
    canonical_job_key: str
    employer: str
    title: str
    location: str | None
    employment_type: str | None
    workplace_type: str | None
    description: str
    source_url: str
    apply_url: str
    fetched_at: str
    content_sha256: str


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value: str) -> str:
    parser = PlainText()
    parser.feed(value)
    return " ".join(parser.parts).strip()


def check_job_url(value: str, external_id: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc != "jobs.lever.co"
            or parsed.path.rstrip("/") not in (
                f"/{BOARD}/{external_id}", f"/{BOARD}/{external_id}/apply")):
        raise ProbeError("UNEXPECTED_JOB_DESTINATION")
    return value


def parse_job(record: dict, timestamp: str) -> Job:
    try:
        external_id = record["id"]
        if str(UUID(external_id)) != external_id.lower():
            raise ProbeError("INVALID_EXTERNAL_ID")
        sections = [record.get("descriptionPlain") or plain(record.get("description", ""))]
        for section in record.get("lists", []):
            sections.extend([section.get("text", ""), plain(section.get("content", ""))])
        sections.append(record.get("additionalPlain") or plain(record.get("additional", "")))
        description = "\n\n".join(s.strip() for s in sections if s and s.strip())
        if not description or not record["text"].strip():
            raise ProbeError("INCOMPLETE_JOB")
        categories = record.get("categories", {})
        return Job(
            external_id=external_id, canonical_job_key=f"lever:{BOARD}:{external_id}",
            employer="Drivetrain", title=record["text"],
            location=categories.get("location"), employment_type=categories.get("commitment"),
            workplace_type=record.get("workplaceType"), description=description,
            source_url=check_job_url(record["hostedUrl"], external_id),
            apply_url=check_job_url(record["applyUrl"], external_id), fetched_at=timestamp,
            content_sha256=hashlib.sha256(description.encode()).hexdigest(),
        )
    except (KeyError, TypeError, AttributeError, ValueError, ValidationError) as error:
        raise ProbeError("SOURCE_SCHEMA_INVALID") from error


def fetch_jobs(client: httpx.Client | None = None) -> tuple[list[Job], int]:
    own_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(25, connect=10), follow_redirects=False)
    try:
        with client.stream("GET", ENDPOINT, headers={"Accept": "application/json"}) as response:
            if response.status_code == 429:
                raise ProbeError("SOURCE_RATE_LIMITED", retry_after=response.headers.get("retry-after"))
            if response.status_code != 200:
                raise ProbeError("SOURCE_UNAVAILABLE")
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE:
                    raise ProbeError("SOURCE_RESPONSE_TOO_LARGE")
        try:
            records = json.loads(body)
        except (ValueError, UnicodeError) as error:
            raise ProbeError("SOURCE_SCHEMA_INVALID") from error
        if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
            raise ProbeError("SOURCE_SCHEMA_INVALID")
        jobs = [parse_job(record, now()) for record in records]
        unique = {job.canonical_job_key: job for job in jobs}
        return list(unique.values()), len(jobs) - len(unique)
    except httpx.TimeoutException as error:
        raise ProbeError("SOURCE_TIMEOUT") from error
    except httpx.RequestError as error:
        raise ProbeError("SOURCE_NETWORK_ERROR") from error
    finally:
        if own_client:
            client.close()


def title_tokens(title: str) -> set[str]:
    aliases = {"engineering": "engineer", "developer": "engineer", "internship": "intern"}
    tokens = {aliases.get(token, token) for token in re.findall(r"[a-z0-9]+", title.lower())}
    if "engineer" in tokens:
        tokens.discard("software")
    return tokens


def match_jobs(jobs: list[Job], title: str, location: str | None = None) -> list[Job]:
    requested = title_tokens(title)
    if not requested:
        raise ProbeError("INVALID_TITLE")
    return [job for job in jobs if requested <= title_tokens(job.title)
            and (location is None or (job.location is not None
                 and location.casefold() in job.location.casefold()))][:5]


def run(title: str, location: str | None) -> dict:
    jobs, duplicates = fetch_jobs()
    matches = match_jobs(jobs, title, location)
    assert not match_jobs(jobs, "CareerLensNonexistentRoleXYZ987654")
    # One repeat GET verifies IDs observed now, not a guarantee of future stability.
    repeat, _ = fetch_jobs()
    ids = {j.external_id for j in jobs}
    repeated_ids = {j.external_id for j in repeat}
    return {
        "status": "PASS", "source": BOARD, "endpoint": ENDPOINT,
        "preferred_title": title, "explicit_location": location,
        "listing_count": len(jobs), "duplicates_removed": duplicates,
        "ids_equal_across_two_reads": ids == repeated_ids,
        "empty_match_test": "PASS", "matches": [j.model_dump() for j in matches],
        "internship_titles": [j.title for j in jobs if "intern" in title_tokens(j.title)],
        "no_results_reason": None if matches else "No title match on the configured board",
        "matching_rule": "All normalized title tokens; engineering/developer aliases; software omitted when engineer present",
        "limitations": ["One board only", "Title matching does not prove eligibility",
                         "No submission API credentials", "Live availability can change"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", default="Software Engineer Intern")
    parser.add_argument("--location")
    args = parser.parse_args()
    try:
        emit("job-source", run(args.title, args.location))
    except Exception as error:
        raise SystemExit(failed("job-source", error))
