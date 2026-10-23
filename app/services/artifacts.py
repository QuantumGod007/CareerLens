from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tempfile
import time
from uuid import uuid4

from app.core.errors import DomainError
from app.persistence.models import Artifact


class ArtifactStore:
    def __init__(self, database):
        self.db = database
        self.root = database.settings.data_dir.resolve() / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise DomainError("UNSAFE_ARTIFACT_PATH", "Artifact storage must be a private directory.", 400)
        self.root.chmod(0o700)

    def safe_path(self, relative):
        candidate = Path(relative)
        if (candidate.is_absolute() or len(candidate.parts) != 1 or candidate.name in {".", ".."}
                or "\\" in relative or not re.fullmatch(r"[0-9a-f-]{36}\.bin", relative)):
            raise DomainError("UNSAFE_ARTIFACT_PATH", "Invalid artifact storage path.", 400)
        path = self.root / candidate
        if path.is_symlink() or path.resolve().parent != self.root.resolve():
            raise DomainError("UNSAFE_ARTIFACT_PATH", "Invalid artifact storage path.", 400)
        return path

    def store(self, content: bytes, owner, media_type="application/octet-stream"):
        if len(content) > 5 * 1024 * 1024:
            raise DomainError("ARTIFACT_TOO_LARGE", "Artifact exceeds the local size limit.", 413)
        secret = self.db.settings.groq_key.get_secret_value().encode()
        if re.search(rb"gsk_[A-Za-z0-9_-]{20,}", content) or (secret and secret in content):
            raise DomainError("SECRET_IN_ARTIFACT", "Credential-like content cannot be stored.", 400)
        if media_type not in {"application/pdf", "application/octet-stream", "image/png"}:
            raise DomainError("UNSUPPORTED_MEDIA", "Unsupported artifact media type.", 415)
        artifact_id = uuid4()
        relative = f"{artifact_id}.bin"
        destination = self.safe_path(relative)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".tmp-", dir=self.root, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            with self.db.write() as session:
                artifact = Artifact(id=artifact_id, session_id=owner, relative_path=relative,
                    sha256=hashlib.sha256(content).hexdigest(), size=len(content), media_type=media_type)
                session.add(artifact)
            return artifact
        except BaseException:
            if temporary:
                temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise

    def read(self, artifact_id, owner):
        with self.db.read() as session:
            artifact = session.get(Artifact, artifact_id)
            if not artifact or artifact.session_id != owner:
                raise DomainError("NOT_FOUND", "Artifact not found.", 404)
            path = self.safe_path(artifact.relative_path)
            try:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as stream:
                    data = stream.read(5 * 1024 * 1024 + 1)
            except OSError:
                raise DomainError("ARTIFACT_UNAVAILABLE", "Artifact file is unavailable.", 404) from None
            if len(data) != artifact.size or hashlib.sha256(data).hexdigest() != artifact.sha256:
                raise DomainError("ARTIFACT_CORRUPT", "Artifact integrity verification failed.", 409)
            return data

    def cleanup_temporary(self, *, older_than_seconds=3600):
        removed = 0
        for path in self.root.glob(".tmp-*"):
            if not path.is_symlink() and path.is_file() and time.time() - path.stat().st_mtime > older_than_seconds:
                path.unlink()
                removed += 1
        return removed
