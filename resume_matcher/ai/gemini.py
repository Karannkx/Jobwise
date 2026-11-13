"""Google Gemini integration (official ``google-genai`` SDK).

Responsibilities: build requests, enforce timeouts, retry transient failures with
exponential backoff + jitter, validate the JSON that comes back, cache successful
responses locally and translate every failure into a clear, user-presentable error.
The API key is read from the settings store each call and is never logged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
from typing import Any, Callable, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import SettingsStore
from ..db import AiCache, Database, utc_now
from ..errors import (
    AIAuthError,
    AIError,
    AINetworkError,
    AINotConfiguredError,
    AIRateLimitError,
    AIResponseError,
)
from ..logging_setup import redact
from ..schemas import (
    JobAnalysis,
    MatchAssessment,
    ParsedResume,
    RoleSuggestions,
    SkillGapAdvice,
)
from . import prompts

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def _extract_json(text: str) -> Any:
    text = _FENCE.sub("", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


class _Retryable(Exception):
    """Internal marker wrapping an AIError that is worth retrying."""

    def __init__(self, error: AIError, retry_after: Optional[float] = None):
        super().__init__(str(error))
        self.error = error
        self.retry_after = retry_after


class GeminiService:
    def __init__(
        self,
        settings: SettingsStore,
        db: Database,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._settings = settings
        self._db = db
        self._sleep = sleep
        self._client = None
        self._client_signature: Optional[tuple] = None

    # ------------------------------------------------------------------ client
    def is_configured(self) -> bool:
        return bool(self._settings.get_api_key())

    def _get_client(self):
        key = self._settings.get_api_key()
        if not key:
            raise AINotConfiguredError(
                "No Gemini API key is configured. Add one in Settings or set the GEMINI_API_KEY "
                "environment variable."
            )
        timeout = self._settings.settings.request_timeout_seconds
        signature = (hashlib.sha256(key.encode()).hexdigest(), timeout)
        if self._client is None or signature != self._client_signature:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=key, http_options=types.HttpOptions(timeout=int(timeout * 1000))
            )
            self._client_signature = signature
        return self._client

    def _raw_generate(self, prompt: str) -> str:
        """One request to Gemini. Raises Retryable-wrapped or final AIErrors."""
        from google.genai import errors as genai_errors
        from google.genai import types

        client = self._get_client()
        try:
            response = client.models.generate_content(
                model=self._settings.settings.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=prompts.SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
        except genai_errors.APIError as exc:
            code = getattr(exc, "code", None)
            message = redact(str(getattr(exc, "message", "") or exc))
            if code in (401, 403) or (code == 400 and "api key" in message.lower()):
                raise AIAuthError(
                    "Gemini rejected the API key. Check the key in Settings and make sure the "
                    "Gemini API is enabled for it."
                ) from exc
            if code == 404:
                raise AIError(
                    f"The model '{self._settings.settings.model}' was not found. "
                    "Pick another model in Settings."
                ) from exc
            if code == 429:
                raise _Retryable(
                    AIRateLimitError(
                        "The Gemini rate limit or quota was reached. Wait a moment and try again."
                    ),
                    retry_after=_retry_after(exc),
                ) from exc
            if code is not None and code >= 500:
                raise _Retryable(
                    AINetworkError("The Gemini service is temporarily unavailable.")
                ) from exc
            log.warning("Gemini request rejected (code=%s): %s", code, message[:200])
            raise AIError(f"Gemini could not process the request (error {code}).") from exc
        except Exception as exc:
            if _is_network_error(exc):
                raise _Retryable(
                    AINetworkError(
                        "Could not reach the Gemini service. Check your internet connection."
                    )
                ) from exc
            log.exception("unexpected Gemini client error")
            raise AIError("An unexpected error occurred while contacting Gemini.") from exc

        text = getattr(response, "text", None)
        if not text:
            raise _Retryable(
                AIResponseError("Gemini returned an empty or blocked response.")
            )
        return text

    # ------------------------------------------------------------------- core
    def _cache_key(self, kind: str, prompt: str) -> str:
        model = self._settings.settings.model
        return hashlib.sha256(f"{kind}\0{model}\0{prompt}".encode("utf-8")).hexdigest()

    def _cache_get(self, key: str, model_cls: Type[T]) -> Optional[T]:
        try:
            with self._db.session() as s:
                row = s.get(AiCache, key)
                if row:
                    return model_cls.model_validate(json.loads(row.response))
        except Exception:
            log.debug("cache read failed", exc_info=True)
        return None

    def _cache_put(self, key: str, kind: str, value: BaseModel) -> None:
        try:
            with self._db.session() as s:
                s.merge(
                    AiCache(
                        cache_key=key,
                        kind=kind,
                        response=value.model_dump_json(),
                        created_at=utc_now(),
                    )
                )
        except Exception:
            log.debug("cache write failed", exc_info=True)

    def clear_cache(self) -> int:
        with self._db.session() as s:
            n = s.query(AiCache).delete()
        return n

    def _call(self, kind: str, prompt: str, model_cls: Type[T], *, use_cache: bool = True) -> T:
        key = self._cache_key(kind, prompt)
        if use_cache:
            cached = self._cache_get(key, model_cls)
            if cached is not None:
                log.info("AI cache hit (%s)", kind)
                return cached

        max_retries = self._settings.settings.max_retries
        attempt = 0
        while True:
            try:
                raw = self._raw_generate(prompt)
                try:
                    result = model_cls.model_validate(_extract_json(raw))
                except (ValueError, ValidationError) as exc:
                    raise _Retryable(
                        AIResponseError(
                            "The AI returned a response that could not be understood. "
                            "Please try again."
                        )
                    ) from exc
                self._cache_put(key, kind, result)
                log.info("AI call ok (%s, attempt %d)", kind, attempt + 1)
                return result
            except _Retryable as retry:
                if attempt >= max_retries:
                    log.warning("AI call failed after %d attempts (%s)", attempt + 1, kind)
                    raise retry.error
                delay = retry.retry_after or min(30.0, 1.5 * (2**attempt))
                delay += random.uniform(0, 0.5)
                log.info("AI call retry %d in %.1fs (%s)", attempt + 1, delay, type(retry.error).__name__)
                self._sleep(delay)
                attempt += 1

    # --------------------------------------------------------------- operations
    def parse_resume(self, text: str) -> ParsedResume:
        text = text[: self._settings.settings.max_resume_chars]
        return self._call("parse_resume", prompts.resume_parse_prompt(text), ParsedResume)

    def analyze_job(self, text: str) -> JobAnalysis:
        text = text[: self._settings.settings.max_resume_chars]
        return self._call("analyze_job", prompts.job_analysis_prompt(text), JobAnalysis)

    def assess_match(self, profile: dict[str, Any], job: dict[str, Any]) -> MatchAssessment:
        prompt = prompts.match_prompt(
            prompts.anonymise_profile(profile), prompts.job_for_prompt(job)
        )
        return self._call("assess_match", prompt, MatchAssessment)

    def skill_gap_advice(
        self, profile: dict[str, Any], missing: list[dict[str, Any]], job_title: str
    ) -> SkillGapAdvice:
        prompt = prompts.gap_prompt(prompts.anonymise_profile(profile), missing, job_title)
        return self._call("skill_gap_advice", prompt, SkillGapAdvice)

    def suggest_roles(self, profile: dict[str, Any], prefs: dict[str, Any]) -> RoleSuggestions:
        prompt = prompts.roles_prompt(prompts.anonymise_profile(profile), prefs)
        return self._call("suggest_roles", prompt, RoleSuggestions)

    def test_connection(self) -> None:
        """Cheap request used by the Settings screen; raises an AIError on failure."""

        class _Ping(BaseModel):
            ok: bool = True

        self._call("ping", 'TASK: ping\nReturn the JSON {"ok": true}', _Ping, use_cache=False)


# ---------------------------------------------------------------------------
def _retry_after(exc: Exception) -> Optional[float]:
    try:
        headers = getattr(getattr(exc, "response", None), "headers", None) or {}
        value = headers.get("retry-after")
        return min(float(value), 60.0) if value else None
    except (TypeError, ValueError):
        return None


def _is_network_error(exc: Exception) -> bool:
    import socket

    names = {c.__name__ for c in type(exc).__mro__}
    if names & {"TransportError", "TimeoutException", "ConnectError", "ReadTimeout", "NetworkError"}:
        return True
    return isinstance(exc, (ConnectionError, TimeoutError, socket.gaierror, socket.timeout))
