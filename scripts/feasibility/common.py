"""Bounded, sanitized output shared by standalone probes."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "data" / "feasibility"


class ProbeError(Exception):
    """A classified error whose code is safe to report."""

    def __init__(self, code: str, *, retry_after: str | None = None):
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


def browser_environment() -> None:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / "data" / "playwright"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(name: str, report: dict) -> None:
    """Only write allowlisted probe results, never SDK exceptions or headers."""
    report = {"observed_at": now(), **report}
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    payload = re.sub(r"gsk_[A-Za-z0-9_-]+", "[REDACTED]", payload)
    OUTPUT.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = OUTPUT / f"{name}.json"
    target.write_text(payload + "\n")
    target.chmod(0o600)
    print(payload)


def failed(name: str, exc: Exception) -> int:
    emit(name, {
        "status": "BLOCKED" if isinstance(exc, ProbeError) else "FAIL",
        "code": exc.code if isinstance(exc, ProbeError) else "UNEXPECTED_ERROR",
        "exception_type": type(exc).__name__,
        "retry_after": exc.retry_after if isinstance(exc, ProbeError) else None,
    })
    return 1
