"""Turning a candidate profile into search queries, and filtering feeds locally."""

from __future__ import annotations

import re
from typing import Any, Optional

from .models import Posting
from .vocab import GENERIC_ROLE_WORDS

_TITLE_NOISE = re.compile(r"\b(i{1,3}|iv|v|level \d|\(.*?\)|- .*$|, .*$)\b", re.I)


def _clean_title(title: str) -> str:
    t = re.sub(r"\(.*?\)", " ", title or "")
    t = re.split(r"\s[-|@,]\s|,", t)[0]
    return re.sub(r"\s+", " ", t).strip()


def build_queries(profile: dict[str, Any], roles: str = "", limit: int = 3) -> list[str]:
    """Role phrases to search for. Explicit roles win; otherwise use recent job titles, then top skills."""
    out: list[str] = []

    def add(q: str) -> None:
        q = re.sub(r"\s+", " ", q).strip()
        if len(q) >= 3 and q.lower() not in {x.lower() for x in out}:
            out.append(q)

    for r in re.split(r"[,;\n]", roles or ""):
        add(r)
    if not out:
        for e in profile.get("experience", [])[:4]:
            add(_clean_title(e.get("title", "")))
            if len(out) >= 2:
                break
    if len(out) < limit:
        skills = [s.get("name", "") for s in profile.get("skills", []) if s.get("category", "technical") in ("technical", "tool", "domain")]
        if skills and not roles.strip():
            add(" ".join(skills[:2]))
    return out[:limit]


def _terms(queries: list[str]) -> tuple[list[str], list[str]]:
    phrases = [q.lower() for q in queries if q.strip()]
    tokens: list[str] = []
    for q in phrases:
        for t in re.split(r"[^a-z0-9+#.]+", q):
            if len(t) >= 3 and t not in GENERIC_ROLE_WORDS and t not in tokens:
                tokens.append(t)
    return phrases, tokens


def is_relevant(posting: Posting, queries: list[str]) -> bool:
    """Loose relevance test for providers that cannot search server-side."""
    if not queries:
        return True
    phrases, tokens = _terms(queries)
    title = posting.title.lower()
    tags = " ".join(posting.tags).lower()
    if any(p in title or p in tags for p in phrases):
        return True
    if any(t in title or t in tags for t in tokens):
        return True
    body = posting.description.lower()
    return sum(1 for t in tokens if t in body) >= 2
