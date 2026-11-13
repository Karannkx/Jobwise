"""Paths, user settings and API-key handling.

* Non-secret preferences live in the SQLite ``app_settings`` table.
* The Gemini API key is **never** stored in the database, source code or logs.
  Lookup order: ``GEMINI_API_KEY`` environment variable, then an owner-only
  ``secret.json`` in the application data folder (written from the Settings screen).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Literal, Optional

from platformdirs import user_data_dir
from pydantic import BaseModel, Field, field_validator

from . import APP_ID
from .db import AppSetting, Database
from .db.session import restrict_permissions

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.1-flash-lite"
API_KEY_ENV = "GEMINI_API_KEY"


def data_dir() -> Path:
    """Application data folder (override with RESUME_MATCHER_HOME)."""
    override = os.environ.get("RESUME_MATCHER_HOME")
    path = Path(override) if override else Path(user_data_dir(APP_ID, appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    restrict_permissions(path)
    return path


class ScoringWeights(BaseModel):
    """Relative weights for the overall score. They are normalised before use."""

    skills: float = Field(0.45, ge=0, le=1)
    experience: float = Field(0.25, ge=0, le=1)
    qualification: float = Field(0.15, ge=0, le=1)
    semantic: float = Field(0.15, ge=0, le=1)

    def as_dict(self) -> dict[str, float]:
        return {
            "skills": self.skills,
            "experience": self.experience,
            "qualification": self.qualification,
            "semantic": self.semantic,
        }


class Settings(BaseModel):
    theme: Literal["light", "dark"] = "light"
    model: str = DEFAULT_MODEL
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    request_timeout_seconds: int = Field(60, ge=10, le=300)
    max_retries: int = Field(4, ge=0, le=8)
    max_resume_chars: int = Field(30000, ge=2000, le=200000)
    batch_concurrency: int = Field(3, ge=1, le=6)
    disclosure_accepted: bool = False
    # job search
    disabled_sources: list[str] = Field(default_factory=list)
    search_country: str = "in"  # ISO code used by country-based providers (Adzuna, Jooble, JSearch)
    ai_verify_top: int = Field(8, ge=0, le=30)
    max_job_age_days: int = Field(45, ge=1, le=365)
    per_source_limit: int = Field(40, ge=5, le=100)

    @field_validator("model")
    @classmethod
    def _model_not_blank(cls, v: str) -> str:
        return v.strip() or DEFAULT_MODEL


class SettingsStore:
    """Thread-safe access to settings and the API key."""

    def __init__(self, db: Database, secret_path: Optional[Path] = None):
        self._db = db
        self._lock = threading.RLock()
        self._secret_path = secret_path or (data_dir() / "secret.json")
        self._settings = self._load()

    # -- settings ---------------------------------------------------------
    def _load(self) -> Settings:
        try:
            with self._db.session() as s:
                row = s.get(AppSetting, "settings")
                if row and row.value:
                    return Settings.model_validate(row.value)
        except Exception:  # corrupted settings must never block start-up
            log.warning("settings could not be loaded; using defaults", exc_info=True)
        return Settings()

    @property
    def settings(self) -> Settings:
        with self._lock:
            return self._settings

    def update(self, **changes) -> Settings:
        with self._lock:
            data = self._settings.model_dump()
            data.update(changes)
            self._settings = Settings.model_validate(data)
            with self._db.session() as s:
                row = s.get(AppSetting, "settings")
                if row is None:
                    s.add(AppSetting(key="settings", value=self._settings.model_dump()))
                else:
                    row.value = self._settings.model_dump()
            return self._settings

    # -- secrets (API keys) -----------------------------------------------
    def _read_all(self) -> dict:
        try:
            data = json.loads(self._secret_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_all(self, data: dict) -> None:
        if not data.get("gemini_api_key") and not data.get("providers"):
            try:
                self._secret_path.unlink()
            except FileNotFoundError:
                pass
            return
        self._secret_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._secret_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        restrict_permissions(tmp)
        tmp.replace(self._secret_path)
        restrict_permissions(self._secret_path)

    def api_key_source(self) -> Optional[str]:
        if os.environ.get(API_KEY_ENV, "").strip():
            return "environment"
        if self._read_secret():
            return "settings"
        return None

    def get_api_key(self) -> Optional[str]:
        env = os.environ.get(API_KEY_ENV, "").strip()
        if env:
            return env
        return self._read_secret()

    def set_api_key(self, key: str) -> None:
        with self._lock:
            data = self._read_all()
            key = key.strip()
            if key:
                data["gemini_api_key"] = key
            else:
                data.pop("gemini_api_key", None)
            self._write_all(data)

    def _read_secret(self) -> Optional[str]:
        key = str(self._read_all().get("gemini_api_key", "")).strip()
        return key or None

    # -- job-provider credentials ---------------------------------------------
    def get_credential(self, provider_id: str, field_id: str, env: Optional[str] = None) -> str:
        """Environment variable first, then the saved value. Empty string when not set."""
        if env:
            val = os.environ.get(env, "").strip()
            if val:
                return val
        return str(self._read_all().get("providers", {}).get(provider_id, {}).get(field_id, "")).strip()

    def credential_source(self, provider_id: str, field_id: str, env: Optional[str] = None) -> Optional[str]:
        if env and os.environ.get(env, "").strip():
            return "environment"
        if str(self._read_all().get("providers", {}).get(provider_id, {}).get(field_id, "")).strip():
            return "settings"
        return None

    def set_credentials(self, provider_id: str, values: dict[str, str]) -> None:
        """Save non-empty values; an empty string for a field removes it."""
        with self._lock:
            data = self._read_all()
            prov = dict(data.get("providers", {}))
            cur = dict(prov.get(provider_id, {}))
            for k, v in values.items():
                v = (v or "").strip()
                if v:
                    cur[k] = v
                else:
                    cur.pop(k, None)
            if cur:
                prov[provider_id] = cur
            else:
                prov.pop(provider_id, None)
            if prov:
                data["providers"] = prov
            else:
                data.pop("providers", None)
            self._write_all(data)
