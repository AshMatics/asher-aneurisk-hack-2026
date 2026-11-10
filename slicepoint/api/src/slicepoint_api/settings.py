"""Service settings, read from the environment (no settings file, no secrets on disk).

==============================  ========================================================
``SLICEPOINT_SERVICE_TOKEN``    bearer token, at least 32 characters (required)
``SLICEPOINT_DATA_ROOT``        folder holding the dataset folders (required)
``SLICEPOINT_RESULTS_DIR``      where jobs and reference profiles are written (required)
``SLICEPOINT_MAX_BODY_BYTES``   request body cap, default 1 MiB
``SLICEPOINT_MAX_CONCURRENT_JOBS``  jobs run at once, default 1
``SLICEPOINT_MAX_QUEUED_JOBS``  queued + running jobs before 503, default 16
``SLICEPOINT_ENABLE_DOCS``      ``1`` serves /docs and /openapi.json, default off
``SLICEPOINT_API_HOST`` / ``SLICEPOINT_API_PORT``  bind address, default 127.0.0.1:8100
==============================  ========================================================

The token is deliberately not ``SLICEPOINT_API_TOKEN``: that name belongs to the GPU
segmentation worker (``slicepoint/segmentation/LOCAL_API.md``), and the two services
should not share a secret.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

MIN_TOKEN_LENGTH = 32


class SettingsError(ValueError):
    """The service is misconfigured and refuses to start."""


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    token: SecretStr
    data_root: Path
    results_dir: Path
    max_body_bytes: int = Field(default=1024 * 1024, gt=0)
    max_concurrent_jobs: int = Field(default=1, ge=1, le=16)
    max_queued_jobs: int = Field(default=16, ge=1)
    enable_docs: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=8100, gt=0, lt=65536)

    @field_validator("token")
    @classmethod
    def _long_enough(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < MIN_TOKEN_LENGTH:
            raise ValueError(f"the service token must be at least {MIN_TOKEN_LENGTH} characters")
        return v

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Settings from ``environ`` (default ``os.environ``). Raises :class:`SettingsError`
        with a one-line message (never the token) if anything is missing or invalid."""
        env = os.environ if environ is None else environ
        missing = [k for k in ("SLICEPOINT_SERVICE_TOKEN", "SLICEPOINT_DATA_ROOT", "SLICEPOINT_RESULTS_DIR")
                   if not env.get(k)]
        if missing:
            raise SettingsError(f"missing environment variable(s): {', '.join(missing)}")
        raw: dict[str, object] = {
            "token": env["SLICEPOINT_SERVICE_TOKEN"],
            "data_root": env["SLICEPOINT_DATA_ROOT"],
            "results_dir": env["SLICEPOINT_RESULTS_DIR"],
            "enable_docs": env.get("SLICEPOINT_ENABLE_DOCS", "0").strip().lower() in ("1", "true", "yes"),
        }
        for key, name in (("max_body_bytes", "SLICEPOINT_MAX_BODY_BYTES"),
                          ("max_concurrent_jobs", "SLICEPOINT_MAX_CONCURRENT_JOBS"),
                          ("max_queued_jobs", "SLICEPOINT_MAX_QUEUED_JOBS"),
                          ("host", "SLICEPOINT_API_HOST"),
                          ("port", "SLICEPOINT_API_PORT")):
            if env.get(name):
                raw[key] = env[name]
        try:
            return cls.model_validate(raw)
        except ValueError as exc:
            raise SettingsError(_first_line(exc)) from None

    def checked(self) -> Settings:
        """Resolve the folders and make sure they are usable; raise :class:`SettingsError` if not."""
        root = self.data_root.expanduser().resolve()
        if not root.is_dir():
            raise SettingsError("SLICEPOINT_DATA_ROOT is not an existing folder")
        results = self.results_dir.expanduser().resolve()
        results.mkdir(parents=True, exist_ok=True)
        if results == root or results.is_relative_to(root):
            raise SettingsError("SLICEPOINT_RESULTS_DIR must not be inside SLICEPOINT_DATA_ROOT")
        return self.model_copy(update={"data_root": root, "results_dir": results})


def _first_line(exc: ValueError) -> str:
    from pydantic import ValidationError

    if isinstance(exc, ValidationError) and exc.errors():
        e = exc.errors()[0]
        loc = ".".join(str(x) for x in e["loc"])
        return f"invalid setting {loc}: {e['msg']}"
    return str(exc).splitlines()[0]
