from app.persistence.models import Event


def append_event(session, entity_type, entity_id, correlation_id, kind, **metadata):
    allowed = {"from_state", "to_state", "revision", "step", "attempt", "error_code", "count", "mode", "role", "decision"}
    session.add(Event(entity_type=entity_type, entity_id=entity_id, correlation_id=correlation_id,
        kind=kind, metadata_json={k: v for k, v in metadata.items() if k in allowed}))
