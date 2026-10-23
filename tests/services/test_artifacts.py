import os
import time
from uuid import uuid4

import pytest

from app.core.config import identity
from app.core.errors import DomainError
from app.persistence.models import Artifact
from app.services.artifacts import ArtifactStore


def test_owned_download_and_tamper_detection(database, client, headers):
    store = ArtifactStore(database)
    artifact = store.store(b"synthetic artifact bytes", identity(database.settings).id)
    response = client.get(f"/api/v1/artifacts/{artifact.id}", headers=headers)
    assert response.status_code == 200 and response.content == b"synthetic artifact bytes"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert store.safe_path(artifact.relative_path).stat().st_mode & 0o077 == 0
    with pytest.raises(DomainError, match="NOT_FOUND"):
        store.read(artifact.id, uuid4())
    store.safe_path(artifact.relative_path).write_bytes(b"tampered")
    assert client.get(f"/api/v1/artifacts/{artifact.id}", headers=headers).status_code == 409


@pytest.mark.parametrize("path", ["../.env", "/etc/passwd", "nested/file", "..\\secret", "not-a-uuid"])
def test_unsafe_paths_are_rejected(database, path):
    with pytest.raises(DomainError, match="UNSAFE_ARTIFACT_PATH"):
        ArtifactStore(database).safe_path(path)


def test_symlinks_and_missing_files_fail_closed(database, tmp_path):
    store = ArtifactStore(database)
    owner = identity(database.settings).id
    artifact = store.store(b"synthetic", owner)
    destination = store.root / artifact.relative_path
    destination.unlink()
    target = tmp_path / "private.txt"
    target.write_text("not allowed")
    destination.symlink_to(target)
    with pytest.raises(DomainError, match="UNSAFE_ARTIFACT_PATH"):
        store.read(artifact.id, owner)
    destination.unlink()
    with pytest.raises(DomainError, match="ARTIFACT_UNAVAILABLE"):
        store.read(artifact.id, owner)


def test_limits_secrets_and_temporary_cleanup(database):
    store = ArtifactStore(database)
    owner = identity(database.settings).id
    with pytest.raises(DomainError, match="ARTIFACT_TOO_LARGE"):
        store.store(b"x" * (5 * 1024 * 1024 + 1), owner)
    with pytest.raises(DomainError, match="SECRET_IN_ARTIFACT"):
        store.store(("gsk_" + "synthetic" * 5).encode(), owner)
    with pytest.raises(DomainError, match="UNSUPPORTED_MEDIA"):
        store.store(b"<script>synthetic</script>", owner, "text/html")
    artifact = store.store(b"keep this", owner)
    temporary = store.root / ".tmp-abandoned"
    temporary.write_bytes(b"temporary")
    os.utime(temporary, (time.time() - 7200, time.time() - 7200))
    assert store.cleanup_temporary() == 1
    assert store.read(artifact.id, owner) == b"keep this"
