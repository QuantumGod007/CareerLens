from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data_dir: Path = ROOT / "data" / "backend"
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:8000", "http://localhost:8000")
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")
    lease_seconds: float = Field(default=15, ge=1, le=300)
    heartbeat_seconds: float = Field(default=2, gt=0, le=30)
    poll_seconds: float = Field(default=0.5, gt=0, le=10)
    retry_seconds: float = Field(default=5, ge=0, le=300)
    groq_key: SecretStr = Field(default=SecretStr(""), repr=False)
    groq_model: Literal["openai/gpt-oss-120b"] = "openai/gpt-oss-120b"

    @property
    def db_path(self) -> Path:
        return self.data_dir.resolve() / "careerlens.db"


def load_settings() -> Settings:
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    values = {"groq_key": env.get("GROQ_API_KEY") or "",
              "groq_model": env.get("GROQ_MODEL") or "openai/gpt-oss-120b"}
    for name in ("lease_seconds", "heartbeat_seconds", "poll_seconds", "retry_seconds"):
        if env.get(f"CAREERLENS_{name.upper()}"):
            values[name] = float(env[f"CAREERLENS_{name.upper()}"])
    if env.get("CAREERLENS_DATA_DIR"):
        values["data_dir"] = Path(env["CAREERLENS_DATA_DIR"]).resolve()
    if env.get("CAREERLENS_ALLOWED_ORIGINS"):
        origins = tuple(env["CAREERLENS_ALLOWED_ORIGINS"].split(","))
        if "*" in origins:
            raise ValueError("Wildcard origins are not allowed")
        values["allowed_origins"] = origins
    settings = Settings(**values)
    if settings.heartbeat_seconds >= settings.lease_seconds / 2:
        raise ValueError("Heartbeat interval must be less than half the lease")
    return settings


@dataclass(frozen=True)
class LocalIdentity:
    id: UUID
    token: str = field(repr=False)


def identity(settings: Settings, *, create: bool = False) -> LocalIdentity:
    directory = settings.data_dir.resolve()
    if create:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    path = directory / "local-session.json"
    if create:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as stream:
                json.dump({"id": str(uuid4()), "token": secrets.token_urlsafe(32)}, stream)
                stream.flush()
                os.fsync(stream.fileno())
    if not path.exists() or path.is_symlink():
        raise RuntimeError("Initialize the database/local session with python -m app.tools.init_db")
    if path.stat().st_mode & 0o077:
        raise RuntimeError("Local session file must have owner-only permissions")
    value = json.loads(path.read_text())
    return LocalIdentity(UUID(value["id"]), value["token"])
