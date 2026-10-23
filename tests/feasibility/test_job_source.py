import httpx
import pytest

from scripts.feasibility.common import ProbeError
from scripts.feasibility.test_job_source import fetch_jobs, match_jobs, parse_job

ID = "11111111-1111-4111-8111-111111111111"


def record(**changes):
    return {
        "id": ID, "text": "Engineering Intern", "categories": {
            "location": "India", "commitment": "Internship"},
        "descriptionPlain": "Synthetic public JD intro", "lists": [{
            "text": "Requirements", "content": "<ul><li>Python</li><li>SQL</li></ul>"}],
        "additionalPlain": "Explicit eligibility details", "workplaceType": "remote",
        "hostedUrl": f"https://jobs.lever.co/drivetrain/{ID}",
        "applyUrl": f"https://jobs.lever.co/drivetrain/{ID}/apply", **changes,
    }


def test_all_jd_sections_are_retained():
    job = parse_job(record(), "synthetic-timestamp")
    assert all(value in job.description for value in (
        "Synthetic public JD intro", "Requirements", "Python", "SQL", "Explicit eligibility details"))
    assert job.canonical_job_key == f"lever:drivetrain:{ID}"


def test_duplicates_and_heuristic_title_matching():
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=[record(), record()]))) as client:
        jobs, count = fetch_jobs(client)
    assert count == 1
    assert len(match_jobs(jobs, "Software Engineer Intern", "India")) == 1
    assert match_jobs(jobs, "CareerLensNonexistentRoleXYZ") == []
    assert match_jobs(jobs, "Engineering Intern", "France") == []


def test_unknown_location_does_not_match_explicit_filter():
    job = parse_job(record(categories={}), "synthetic-timestamp")
    assert job.location is None
    assert match_jobs([job], "Engineering Intern", "India") == []
    assert len(match_jobs([job], "Engineering Intern")) == 1


@pytest.mark.parametrize("response, expected", [
    (httpx.Response(503), "SOURCE_UNAVAILABLE"),
    (httpx.Response(429, headers={"retry-after": "20"}), "SOURCE_RATE_LIMITED"),
    (httpx.Response(200, text="not json"), "SOURCE_SCHEMA_INVALID"),
    (httpx.Response(200, json={"jobs": []}), "SOURCE_SCHEMA_INVALID"),
    (httpx.Response(302, headers={"location": "http://127.0.0.1"}), "SOURCE_UNAVAILABLE"),
])
def test_failed_sources_are_explicit(response, expected):
    with httpx.Client(transport=httpx.MockTransport(lambda request: response)) as client:
        with pytest.raises(ProbeError, match=expected):
            fetch_jobs(client)


def test_timeout_does_not_become_empty_results():
    def timeout(request):
        raise httpx.ReadTimeout("Synthetic timeout")
    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(ProbeError, match="SOURCE_TIMEOUT"):
            fetch_jobs(client)


def test_empty_source_stays_empty():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))) as client:
        assert fetch_jobs(client) == ([], 0)


def test_source_size_limit():
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b" " * (3 * 1024 * 1024 + 1)))) as client:
        with pytest.raises(ProbeError, match="SOURCE_RESPONSE_TOO_LARGE"):
            fetch_jobs(client)


@pytest.mark.parametrize("url", ["http://127.0.0.1/private", "https://evil.example.invalid/apply",
                                f"https://jobs.lever.co/other/{ID}/apply"])
def test_unconfigured_destinations_rejected(url):
    with pytest.raises(ProbeError, match="UNEXPECTED_JOB_DESTINATION"):
        parse_job(record(applyUrl=url), "synthetic-timestamp")
