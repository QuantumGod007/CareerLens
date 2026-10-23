import subprocess

from scripts.feasibility.common import ROOT


def test_secret_and_artifact_paths_are_ignored():
    for path in [".env", ".env.local", "data/feasibility/result.json", ".venv/example", "traces/example"]:
        assert subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0
    assert subprocess.run(["git", "check-ignore", "-q", ".env.example"], cwd=ROOT).returncode == 1


def test_env_is_not_tracked_and_template_has_no_key():
    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    assert ".env" not in tracked
    assert "gsk_" not in (ROOT / ".env.example").read_text()
