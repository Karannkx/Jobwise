"""Deterministic, configurable scoring.

The overall score is a weighted blend of

* skill coverage          (deterministic, importance-weighted)
* experience              (years vs. requirement)
* qualification           (education level + certifications)
* semantic fit            (the LLM's 0-100 judgement of responsibilities/projects)

so that no single LLM number decides the outcome. Components that cannot be computed
(e.g. the job states no experience requirement, or the AI is unavailable) are dropped
and the remaining weights are re-normalised; this is recorded as an uncertainty.
Protected attributes are never inputs to any function in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable, Optional

from .config import ScoringWeights

# ---------------------------------------------------------------------------
# Skill normalisation
# ---------------------------------------------------------------------------
ALIASES = {
    "js": "javascript", "ecmascript": "javascript", "ts": "typescript", "py": "python",
    "python3": "python", "ml": "machine learning", "dl": "deep learning",
    "nlp": "natural language processing", "cv": "computer vision", "k8s": "kubernetes",
    "postgres": "postgresql", "psql": "postgresql", "amazon web services": "aws",
    "gcp": "google cloud", "google cloud platform": "google cloud", "node": "node.js",
    "nodejs": "node.js", "node js": "node.js", "reactjs": "react", "react.js": "react",
    "vuejs": "vue", "vue.js": "vue", "angularjs": "angular", "c sharp": "c#", "cpp": "c++",
    "c plus plus": "c++", "scikit learn": "scikit-learn", "sklearn": "scikit-learn",
    "tf": "tensorflow", "mongo": "mongodb", "ms excel": "excel", "microsoft excel": "excel",
    "golang": "go", "dotnet": ".net", "asp.net core": ".net", "ci cd": "ci/cd",
    "cicd": "ci/cd", "rest": "rest api", "restful api": "rest api", "restful apis": "rest api",
    "rest apis": "rest api", "oop": "object-oriented programming", "ux": "ux design",
    "ai": "artificial intelligence", "gen ai": "generative ai", "genai": "generative ai",
    "llms": "llm", "large language models": "llm", "large language model": "llm",
    "power bi": "powerbi", "ms sql server": "sql server", "mssql": "sql server",
}

WEIGHT_BY_IMPORTANCE = {"must_have": 3.0, "important": 2.0, "nice_to_have": 1.0}
CREDIT = {"listed": 1.0, "mentioned": 0.8, "equivalent": 0.7, "missing": 0.0}


def norm_skill(name: str) -> str:
    s = (name or "").lower().strip()
    s = s.replace("&", " and ")
    s = re.sub(r"[\[\](){}]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .,;:-/")
    return ALIASES.get(s, s)


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[\s/,-]+", s) if t]


def _loose_equal(required: str, held: str) -> bool:
    """Does ``held`` satisfy ``required``?

    Directional word-containment: a more specific held skill satisfies a general
    requirement ("sql server" satisfies "sql"), never the reverse ("react" does not
    satisfy "react native"). Small typos are tolerated for longer names.
    """
    if required == held:
        return True
    tr, th = _tokens(required), _tokens(held)
    if tr and th and len(tr) < len(th) and all(t in th for t in tr):
        if len("".join(tr)) >= 2:  # single letters like "r" / "c" must match exactly
            return True
    if min(len(required), len(held)) >= 6 and SequenceMatcher(None, required, held).ratio() >= 0.9:
        return True
    return False


def _mentioned_in_text(skill_norm: str, text: str) -> bool:
    if len(skill_norm) < 2 or not text:
        return False
    pattern = r"(?<![\w+#.])" + re.escape(skill_norm) + r"(?![\w+#])"
    return re.search(pattern, text.lower()) is not None


def candidate_text_blob(profile: dict[str, Any]) -> str:
    parts = [profile.get("summary", "")]
    for e in profile.get("experience", []):
        parts += [e.get("title", ""), e.get("description", "")]
    for p in profile.get("projects", []):
        parts += [p.get("name", ""), p.get("description", ""), " ".join(p.get("technologies", []))]
    parts += profile.get("certifications", [])
    return "\n".join(str(p) for p in parts if p)


# ---------------------------------------------------------------------------
@dataclass
class SkillMatch:
    skill: str
    importance: str
    status: str  # listed | mentioned | equivalent | missing
    via: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.skill, "importance": self.importance, "status": self.status, "via": self.via}


def match_skills(
    job_skills: Iterable[dict[str, Any]],
    profile: dict[str, Any],
    equivalences: Optional[dict[str, str]] = None,
) -> list[SkillMatch]:
    cand = {norm_skill(s.get("name", "")): s.get("name", "") for s in profile.get("skills", [])}
    cand.pop("", None)
    blob = candidate_text_blob(profile)
    eq = {norm_skill(k): v for k, v in (equivalences or {}).items()}
    out: list[SkillMatch] = []
    for js in job_skills:
        name = js.get("name", "")
        importance = js.get("importance", "important")
        jn = norm_skill(name)
        if not jn:
            continue
        hit = next((orig for cn, orig in cand.items() if _loose_equal(jn, cn)), None)
        if hit:
            out.append(SkillMatch(name, importance, "listed", hit))
        elif _mentioned_in_text(jn, blob):
            out.append(SkillMatch(name, importance, "mentioned", "work/project descriptions"))
        elif jn in eq:
            out.append(SkillMatch(name, importance, "equivalent", eq[jn]))
        else:
            out.append(SkillMatch(name, importance, "missing"))
    return out


def skill_score(matches: list[SkillMatch]) -> Optional[float]:
    total = sum(WEIGHT_BY_IMPORTANCE.get(m.importance, 2.0) for m in matches)
    if total == 0:
        return None
    got = sum(WEIGHT_BY_IMPORTANCE.get(m.importance, 2.0) * CREDIT[m.status] for m in matches)
    return round(100.0 * got / total, 1)


def experience_score(candidate_years: float, required_years: Optional[float]) -> Optional[float]:
    if required_years is None:
        return None
    if required_years <= 0:
        return 100.0
    return round(min(100.0, 100.0 * max(candidate_years, 0.0) / required_years), 1)


# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------
LEVELS = {"none": 0, "high_school": 1, "diploma": 2, "bachelor": 3, "master": 4, "doctorate": 5}
_LEVEL_PATTERNS = [
    (5, r"ph\.?\s?d|doctor"),
    (4, r"master|m\.?\s?sc|\bmba\b|m\.?\s?tech|\bm\.?\s?e\b|\bm\.?\s?s\b|\bmca\b|\bmsc\b"),
    (3, r"bachelor|b\.?\s?sc|b\.?\s?tech|\bb\.?\s?e\b|\bb\.?\s?a\b|\bb\.?\s?s\b|\bbca\b|undergraduate|\bbsc\b"),
    (2, r"associate|diploma"),
    (1, r"high school|secondary|\bhsc\b|\bssc\b|a-?levels?|12th"),
]


def level_rank(value: Optional[str]) -> int:
    """Map an enum value ('bachelor') or free text ('B.Sc. in CS') to 0-5."""
    if not value:
        return 0
    v = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if v in LEVELS:
        return LEVELS[v]
    text = str(value).lower()
    for rank, pat in _LEVEL_PATTERNS:
        if re.search(pat, text):
            return rank
    return 0


def highest_education(profile: dict[str, Any]) -> int:
    best = 0
    for e in profile.get("education", []):
        best = max(best, level_rank(e.get("level")), level_rank(e.get("degree")))
    return best


def qualification_score(
    candidate_level: int,
    required_level: Optional[str],
    required_certs: list[str],
    candidate_certs: list[str],
) -> Optional[float]:
    parts: list[tuple[float, float]] = []  # (score, weight)
    req = level_rank(required_level)
    if req > 0:
        s = 100.0 if candidate_level >= req else max(0.0, 100.0 - 35.0 * (req - candidate_level))
        parts.append((s, 0.7))
    if required_certs:
        have = [norm_skill(c) for c in candidate_certs]
        got = sum(1 for rc in required_certs if any(_loose_equal(norm_skill(rc), h) for h in have))
        parts.append((100.0 * got / len(required_certs), 0.3 if parts else 1.0))
    if not parts:
        return None
    total_w = sum(w for _, w in parts)
    return round(sum(s * w for s, w in parts) / total_w, 1)


# ---------------------------------------------------------------------------
@dataclass
class MatchComputation:
    overall: float
    skill: Optional[float]
    experience: Optional[float]
    qualification: Optional[float]
    semantic: Optional[float]
    skill_matches: list[SkillMatch] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    weights_used: dict[str, float] = field(default_factory=dict)


def combine(
    weights: ScoringWeights,
    skill: Optional[float],
    experience: Optional[float],
    qualification: Optional[float],
    semantic: Optional[float],
) -> tuple[float, dict[str, float], list[str]]:
    comps = {"skills": skill, "experience": experience, "qualification": qualification, "semantic": semantic}
    w = weights.as_dict()
    notes: list[str] = []
    labels = {
        "skills": "The job lists no skills, so skill coverage was not scored.",
        "experience": "The job states no experience requirement, so experience was not scored.",
        "qualification": "The job states no education or certification requirement, so qualifications were not scored.",
        "semantic": "AI semantic assessment was unavailable, so the score uses structured criteria only.",
    }
    active = {k: v for k, v in comps.items() if v is not None and w[k] > 0}
    for k, v in comps.items():
        if v is None:
            notes.append(labels[k])
    total_w = sum(w[k] for k in active)
    if not active or total_w == 0:
        return 0.0, {}, notes + ["No scoring criteria were available."]
    overall = sum(comps[k] * w[k] for k in active) / total_w
    used = {k: round(w[k] / total_w, 3) for k in active}
    return round(max(0.0, min(100.0, overall)), 1), used, notes


def preference_concerns(
    job: dict[str, Any], *, pref_mode: Optional[str], pref_location: Optional[str]
) -> list[str]:
    out = []
    jm = (job.get("work_mode") or "").lower()
    if pref_mode and jm and pref_mode.lower() != jm:
        out.append(f"Work-mode preference ({pref_mode}) differs from the role ({jm}).")
    jl = (job.get("location") or "").lower()
    if pref_location and jl and jm != "remote" and pref_location.lower() not in jl and jl not in pref_location.lower():
        out.append(f"Preferred location ({pref_location}) differs from the role location ({job.get('location')}).")
    return out


# ---------------------------------------------------------------------------
# Experience fit (used to rank job-search results "for this person")
# ---------------------------------------------------------------------------
@dataclass
class ExperienceFit:
    label: str  # good | stretch | reach | over | unknown
    text: str
    penalty: float  # points subtracted from the score when ordering results


def experience_fit(candidate_years: float, required_years: Optional[float]) -> ExperienceFit:
    """How well the seniority of a role matches the candidate.

    The weighted score already rewards meeting a requirement; this adds the other side of the story:
    roles far above the candidate are a reach, and roles far below are poor use of their experience.
    """
    if required_years is None:
        return ExperienceFit("unknown", "Required experience not stated", 0.0)
    cand = max(candidate_years or 0.0, 0.0)
    req = max(required_years, 0.0)
    if req == 0:
        if cand > 4:
            return ExperienceFit("over", f"Entry-level role; you have {cand:g} years", min(12.0, (cand - 4) * 1.5))
        return ExperienceFit("good", "Entry-level role", 0.0)
    if cand >= req:
        limit = req + max(4.0, 1.5 * req)
        if cand > limit:
            return ExperienceFit("over", f"Asks {req:g} yrs; you have {cand:g}", min(12.0, (cand - limit) * 1.5 + 3))
        return ExperienceFit("good", f"Asks {req:g} yrs; you have {cand:g}", 0.0)
    ratio = cand / req
    if ratio >= 0.75:
        return ExperienceFit("good", f"Asks {req:g} yrs; you have {cand:g} (close)", 0.0)
    if ratio >= 0.5:
        return ExperienceFit("stretch", f"Asks {req:g} yrs; you have {cand:g}", 3.0)
    return ExperienceFit("reach", f"Asks {req:g} yrs; you have {cand:g}", 8.0)


def preference_penalty(job_work_mode: Optional[str], job_location: Optional[str],
                       pref_mode: Optional[str], pref_location: Optional[str]) -> float:
    """Small ordering penalty when a role clearly conflicts with the stated work-mode / location."""
    pen = 0.0
    jm = (job_work_mode or "").lower()
    if pref_mode and jm and pref_mode.lower() != jm:
        pen += 6.0
    jl = (job_location or "").lower()
    if pref_location and jl and jm != "remote" and pref_location.lower() not in jl and jl not in pref_location.lower():
        pen += 6.0
    return min(pen, 10.0)
