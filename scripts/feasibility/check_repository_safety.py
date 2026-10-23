"""Check tracked/staged files and reachable history without printing credentials."""

from __future__ import annotations

import re
import json
import os
import subprocess
from pathlib import Path, PurePosixPath

from dotenv import dotenv_values

from scripts.feasibility.common import ROOT, emit

KEY_PATTERN = re.compile(rb"gsk_[A-Za-z0-9_-]{20,}")
PRIVATE_DIRS = {"data", "resumes", "uploads", "artifacts", "traces", "screenshots", "browser-state", ".venv"}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def private_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return (any(part in PRIVATE_DIRS for part in parts)
            or (PurePosixPath(path).name.startswith(".env") and PurePosixPath(path).name != ".env.example"))


def check() -> dict:
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    key = env.get("GROQ_API_KEY")
    secrets = [key.encode()] if key else []
    local_file = Path(env.get("CAREERLENS_DATA_DIR") or ROOT / "data" / "backend") / "local-session.json"
    if local_file.exists():
        token = json.loads(local_file.read_text()).get("token")
        if token:
            secrets.append(token.encode())
    tracked = git("ls-files", "-z").decode().split("\0")
    violations = []
    # Index bytes are what a commit would publish; never print matching contents.
    for path in filter(None, tracked):
        if private_path(path):
            violations.append({"path": path, "reason": "private_path_in_index"})
        content = git("show", f":{path}")
        if KEY_PATTERN.search(content) or any(secret in content for secret in secrets):
            violations.append({"path": path, "reason": "credential_in_index"})
    # Verify the supplied credential is absent from all reachable file blobs too.
    objects = git("rev-list", "--objects", "--all").splitlines()
    blobs_checked = 0
    for entry in objects:
        sha = entry.split(b" ", 1)[0].decode()
        if git("cat-file", "-t", sha).strip() != b"blob":
            continue
        blobs_checked += 1
        content = git("cat-file", "blob", sha)
        if KEY_PATTERN.search(content) or any(secret in content for secret in secrets):
            violations.append({"object": sha, "reason": "credential_in_history"})
    ignored = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT).returncode == 0
    return {"status": "PASS" if ignored and not violations else "FAIL",
            "env_ignored": ignored, "tracked_files_checked": len(list(filter(None, tracked))),
            "history_blobs_checked": blobs_checked, "violations": violations,
            "credential_values_reported": False}


if __name__ == "__main__":
    result = check()
    emit("repository-safety", result)
    raise SystemExit(0 if result["status"] == "PASS" else 1)
