"""Logging with redaction of secrets and personal data.

Application code should never log resume content. As a second line of defence,
every record passes through a filter that masks API keys, e-mail addresses and
phone-number-like strings.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_PATTERNS = [
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)(api[_-]?key[\"'=:\s]+)[^\s\"',}]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[REDACTED_EMAIL]"),
    (re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)"), "[REDACTED_PHONE]"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # malformed format args - never let logging crash the app
            message = str(record.msg)
        record.msg = redact(message)
        record.args = ()
        if record.exc_info:
            # Render and redact the traceback text as well.
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def setup_logging(log_dir: Path, level: int = logging.INFO) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(getattr(h, "_resume_matcher", False) for h in root.handlers):
        return
    handler = RotatingFileHandler(
        log_dir / "resume_matcher.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler._resume_matcher = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    root.setLevel(level)
    # Third-party libraries can be chatty about request details.
    for noisy in ("httpx", "httpcore", "google_genai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
