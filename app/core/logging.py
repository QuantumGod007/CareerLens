"""Metadata-only logging: bodies, URLs, credentials and exception text are excluded."""
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("careerlens")


def configure() -> None:
    logger.setLevel(logging.INFO)
    if not logger.hasHandlers():
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)


def record(event: str, **metadata) -> None:
    allowed = {"correlation_id", "task_id", "step", "attempt", "duration_ms", "status_code", "error_code"}
    safe = {key: str(value) for key, value in metadata.items() if key in allowed and value is not None}
    logger.info(json.dumps({"event": event, "timestamp": datetime.now(timezone.utc).isoformat(), **safe}))
