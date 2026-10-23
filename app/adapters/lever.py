"""Reuse Phase 1's bounded validated reader for one configured public board."""
from app.core.errors import DomainError
from scripts.feasibility.test_job_source import fetch_jobs


def fetch_board(board):
    if (board.family != "lever" or board.slug != "drivetrain" or not board.enabled
            or set(board.allowed_hosts) != {"api.lever.co", "jobs.lever.co"}):
        raise DomainError("SOURCE_NOT_ALLOWED", "The board is not a supported configured destination.", 400)
    return fetch_jobs()
