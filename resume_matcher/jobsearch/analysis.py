"""Local (no-AI) job analysis: skills, required experience, education and work mode from raw text.

This produces the same structure the AI job analysis does, so the normal scoring code can score
every search result immediately. The top results are then re-analysed by the AI for accuracy.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from .. import scoring
from .models import Posting
from .vocab import SKILLS

_NICE = re.compile(r"\b(nice[- ]to[- ]have|preferred|bonus|good to have|a plus|is a plus|desirable|advantage|optional|plus)\b", re.I)
_MUST = re.compile(r"\b(required|requirements?|must[- ]have|must|essential|mandatory|minimum qualifications?)\b", re.I)
_HEAD_NICE = re.compile(r"(nice[- ]to[- ]have|preferred|bonus|good to have|desirable|plus|optional|advantage)", re.I)
_HEAD_REQ = re.compile(r"(requirements?|qualifications?|must[- ]have|required|what you.?ll need|what we.?re looking for|you have|about you|essential|skills|who you are)", re.I)

_YEARS = re.compile(r"(\d{1,2})(?:\s*(?:-|–|to)\s*(\d{1,2}))?\s*\+?\s*(?:years?|yrs?)\b", re.I)
_EXP_CTX = re.compile(r"experience|exp\b|background|worked|working", re.I)

SENIORITY = [  # (regex on title, years, label)
    (re.compile(r"\b(intern(ship)?|trainee|apprentice)\b", re.I), 0.0, "intern"),
    (re.compile(r"\b(junior|jr\.?|entry[- ]level|graduate|fresher|associate)\b", re.I), 1.0, "junior"),
    (re.compile(r"\b(head of|director|vp|vice president|chief)\b", re.I), 10.0, "executive"),
    (re.compile(r"\b(principal|staff|architect)\b", re.I), 8.0, "principal"),
    (re.compile(r"\b(lead|manager)\b", re.I), 6.0, "lead"),
    (re.compile(r"\b(senior|sr\.?)\b", re.I), 5.0, "senior"),
]

_EDU = [
    (5, re.compile(r"\b(ph\.?d|doctorate)\b", re.I)),
    (4, re.compile(r"\b(master'?s?|m\.?sc|m\.?tech|mba|m\.?s\.? degree)\b", re.I)),
    (3, re.compile(r"\b(bachelor'?s?|b\.?sc|b\.?tech|b\.?e\.?|undergraduate|bca|bs degree|ba degree|university degree|degree)\b", re.I)),
]
_LEVEL_NAME = {5: "doctorate", 4: "master", 3: "bachelor"}


def level_from_years(years: float) -> str:
    return "entry" if years < 2 else "mid" if years < 6 else "senior"


def seniority_hint(title: str) -> tuple[Optional[float], Optional[str]]:
    for rx, years, label in SENIORITY:
        if rx.search(title or ""):
            return years, label
    return None, None


def stated_years(text: str) -> Optional[float]:
    """Highest 'N years ... experience' requirement mentioned in the text (lower bound of ranges)."""
    best: Optional[float] = None
    for m in _YEARS.finditer(text):
        window = text[max(0, m.start() - 70): m.end() + 70]
        if not _EXP_CTX.search(window):
            continue
        val = float(m.group(1))
        if 0 < val <= 20:
            best = val if best is None else max(best, val)
    return best


def required_education(text: str) -> Optional[str]:
    """Lowest degree level the posting asks for when it mentions one in a requirement context."""
    levels = [lvl for lvl, rx in _EDU if rx.search(text)]
    if not levels:
        return None
    if re.search(r"\b(or equivalent|or related|or higher|and above|preferred)\b", text, re.I) and 3 in levels:
        return "bachelor"
    # A master/PhD mention without "required" is usually "preferred": fall back to the lowest level seen.
    if max(levels) >= 4 and not re.search(r"(master|ph\.?d|doctorate)[^.\n]{0,40}(required|must)|(required|must)[^.\n]{0,40}(master|ph\.?d|doctorate)", text, re.I):
        return _LEVEL_NAME[min(levels)]
    return _LEVEL_NAME[max(levels)]


def work_mode(posting: Posting) -> Optional[str]:
    blob = f"{posting.title} {posting.location or ''}".lower()
    if posting.remote or re.search(r"\bremote\b|work from home|\bwfh\b", blob):
        return "remote"
    text = posting.description.lower()
    if re.search(r"\bhybrid\b", blob) or re.search(r"\bhybrid\b", text[:1500]):
        return "hybrid"
    if re.search(r"\bon[- ]?site\b|\bin[- ]office\b", text[:3000]):
        return "on-site"
    if re.search(r"\bfully remote\b|\bremote[- ]first\b|\b100% remote\b", text):
        return "remote"
    return None


class SkillExtractor:
    """Compiled once per search (the candidate's own skills are added so unusual ones still match)."""

    def __init__(self, extra_terms: Iterable[str] = ()):
        spelling: dict[str, str] = {}
        for canon, variants in SKILLS.items():
            for s in [canon, *variants]:
                spelling[s.lower()] = canon
        for term in extra_terms:
            n = scoring.norm_skill(term)
            if len(n) >= 3 and n not in spelling:
                spelling[n] = n
        self._canon = spelling
        ordered = sorted(spelling, key=len, reverse=True)
        alt = "|".join(re.escape(s) for s in ordered)
        self._rx = re.compile(rf"(?<![A-Za-z0-9+#.])({alt})(?![A-Za-z0-9+#])", re.I)

    def extract(self, title: str, text: str) -> list[dict[str, str]]:
        found: dict[str, str] = {}
        rank = {"nice_to_have": 0, "important": 1, "must_have": 2}

        def note(canon: str, importance: str) -> None:
            if canon not in found or rank[importance] > rank[found[canon]]:
                found[canon] = importance

        for m in self._rx.finditer(title or ""):
            note(self._canon[m.group(1).lower()], "must_have")

        section: Optional[str] = None
        for raw in (text or "").splitlines():
            line = raw.strip(" -*•\t")
            if not line:
                continue
            is_heading = len(line) <= 80 and (line.endswith(":") or (len(line.split()) <= 7 and not line.endswith((".", ";", ","))))
            if is_heading and not self._rx.search(line):
                if _HEAD_NICE.search(line):
                    section = "nice_to_have"
                elif _HEAD_REQ.search(line):
                    section = "must_have"
                else:
                    section = None
            importance = section or "important"
            if _NICE.search(line) and not is_heading:
                importance = "nice_to_have"
            elif _MUST.search(line) and not is_heading and importance != "nice_to_have":
                importance = "must_have"
            for m in self._rx.finditer(line):
                note(self._canon[m.group(1).lower()], importance)
        return [{"name": k, "importance": v} for k, v in found.items()]


def analyse_posting(posting: Posting, extractor: SkillExtractor) -> dict[str, Any]:
    """Structure compatible with ``schemas.JobAnalysis`` (plus ``analysis_source``)."""
    text = posting.description or ""
    years = stated_years(text)
    years_source = "stated" if years is not None else None
    if years is None:
        hint, _label = seniority_hint(posting.title)
        if hint is not None:
            years, years_source = hint, "inferred from title"
    return {
        "title": posting.title,
        "company": posting.company,
        "location": posting.location,
        "work_mode": work_mode(posting),
        "required_experience_years": years,
        "years_source": years_source,
        "required_education": required_education(text),
        "skills": extractor.extract(posting.title, text),
        "certifications": [],
        "responsibilities": [],
        "summary": "",
        "analysis_source": "local",
    }
