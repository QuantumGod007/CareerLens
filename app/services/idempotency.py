import hashlib
import json

from sqlalchemy import select

from app.core.errors import DomainError
from app.persistence.models import IdempotencyRecord


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def previous_response(session, local_id, route, key, request_hash):
    record = session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.session_id == local_id,
        IdempotencyRecord.route == route, IdempotencyRecord.key == key))
    if record and record.request_hash != request_hash:
        raise DomainError("IDEMPOTENCY_CONFLICT", "This key was used for a different request.")
    return record.response_json if record else None
