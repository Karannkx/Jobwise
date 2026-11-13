"""Pydantic models describing the JSON the AI must return.

They are deliberately lenient (unknown keys ignored, ``null`` treated as "missing",
bare strings accepted where an object is expected) because LLM output varies, but
every response is validated before it is stored or used.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _to_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = _NUM.search(value)
        if m:
            return float(m.group(0).replace(",", "."))
    return None


class Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    _str_field: ClassVar[Optional[str]] = None

    @model_validator(mode="before")
    @classmethod
    def _prepare(cls, data: Any) -> Any:
        if isinstance(data, str) and cls._str_field:
            return {cls._str_field: data}
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    out = []
    for item in value:
        if isinstance(item, dict):  # e.g. {"name": "AWS Certified ..."}
            item = item.get("name") or item.get("title") or next(iter(item.values()), "")
        text = str(item).strip()
        if text:
            out.append(text)
    return out


# --------------------------------------------------------------------------
# Resume
# --------------------------------------------------------------------------
class SkillItem(Lenient):
    _str_field = "name"
    name: str
    category: str = "technical"  # technical | soft | tool | domain
    proficiency: Optional[str] = None  # beginner | intermediate | advanced | expert


class ExperienceItem(Lenient):
    _str_field = "title"
    title: str = ""
    company: str = ""
    start: Optional[str] = None
    end: Optional[str] = None
    duration_months: Optional[int] = None
    description: str = ""

    @field_validator("duration_months", mode="before")
    @classmethod
    def _months(cls, v):
        f = _to_float(v)
        return None if f is None else max(0, int(round(f)))

    @field_validator("start", "end", mode="before")
    @classmethod
    def _dates(cls, v):
        return None if v is None else str(v)


class EducationItem(Lenient):
    _str_field = "degree"
    degree: str = ""
    field: str = ""
    institution: str = ""
    year: Optional[str] = None
    # high_school | diploma | bachelor | master | doctorate | other
    level: str = "other"

    @field_validator("year", mode="before")
    @classmethod
    def _year(cls, v):
        return None if v is None else str(v)


class ProjectItem(Lenient):
    _str_field = "name"
    name: str = ""
    description: str = ""
    technologies: list[str] = Field(default_factory=list)

    @field_validator("technologies", mode="before")
    @classmethod
    def _tech(cls, v):
        return _str_list(v)


class ParsedResume(Lenient):
    name: str = "Unknown"
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    summary: str = ""
    skills: list[SkillItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    total_experience_years: float = 0.0

    @field_validator("certifications", "languages", mode="before")
    @classmethod
    def _lists(cls, v):
        return _str_list(v)

    @field_validator("skills", "education", "experience", "projects", mode="before")
    @classmethod
    def _none_to_list(cls, v):
        return [] if v is None else v

    @field_validator("total_experience_years", mode="before")
    @classmethod
    def _years(cls, v):
        f = _to_float(v)
        return 0.0 if f is None else max(0.0, min(f, 60.0))


# --------------------------------------------------------------------------
# Job description
# --------------------------------------------------------------------------
class JobSkill(Lenient):
    _str_field = "name"
    name: str
    importance: str = "important"  # must_have | important | nice_to_have

    @field_validator("importance", mode="before")
    @classmethod
    def _importance(cls, v):
        s = str(v or "").lower().replace("-", "_").replace(" ", "_")
        if s in {"must_have", "must", "required", "critical", "essential", "mandatory"}:
            return "must_have"
        if s in {"nice_to_have", "nice", "preferred", "optional", "bonus", "plus"}:
            return "nice_to_have"
        return "important"


class JobAnalysis(Lenient):
    title: str = "Untitled role"
    company: Optional[str] = None
    location: Optional[str] = None
    work_mode: Optional[str] = None  # remote | hybrid | on-site
    required_experience_years: Optional[float] = None
    # high_school | diploma | bachelor | master | doctorate | none
    required_education: Optional[str] = None
    skills: list[JobSkill] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    summary: str = ""

    @field_validator("required_experience_years", mode="before")
    @classmethod
    def _years(cls, v):
        return _to_float(v)

    @field_validator("certifications", "responsibilities", mode="before")
    @classmethod
    def _lists(cls, v):
        return _str_list(v)

    @field_validator("skills", mode="before")
    @classmethod
    def _skills(cls, v):
        return [] if v is None else v

    @field_validator("work_mode", mode="before")
    @classmethod
    def _mode(cls, v):
        if v is None:
            return None
        s = str(v).lower().replace("_", "-").strip()
        if "remote" in s:
            return "remote"
        if "hybrid" in s:
            return "hybrid"
        if "site" in s or "office" in s or "onsite" in s:
            return "on-site"
        return None


# --------------------------------------------------------------------------
# Match / gap / recommendations
# --------------------------------------------------------------------------
class SkillEquivalence(Lenient):
    job_skill: str
    candidate_skill: str


class MatchAssessment(Lenient):
    semantic_score: float = 0.0
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    explanation: str = ""
    skill_equivalences: list[SkillEquivalence] = Field(default_factory=list)

    @field_validator("semantic_score", mode="before")
    @classmethod
    def _score(cls, v):
        f = _to_float(v)
        return 0.0 if f is None else max(0.0, min(100.0, f))

    @field_validator("strengths", "concerns", "uncertainties", mode="before")
    @classmethod
    def _lists(cls, v):
        return _str_list(v)

    @field_validator("skill_equivalences", mode="before")
    @classmethod
    def _eq(cls, v):
        return [x for x in (v or []) if isinstance(x, dict)]


class GapItem(Lenient):
    _str_field = "skill"
    skill: str
    difficulty: str = "moderate"  # easy | moderate | hard
    estimated_weeks: Optional[int] = None
    learning_path: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)

    @field_validator("difficulty", mode="before")
    @classmethod
    def _diff(cls, v):
        s = str(v or "moderate").lower()
        return s if s in {"easy", "moderate", "hard"} else "moderate"

    @field_validator("estimated_weeks", mode="before")
    @classmethod
    def _weeks(cls, v):
        f = _to_float(v)
        return None if f is None else max(0, int(round(f)))

    @field_validator("learning_path", "certifications", "projects", mode="before")
    @classmethod
    def _lists(cls, v):
        return _str_list(v)


class SkillGapAdvice(Lenient):
    items: list[GapItem] = Field(default_factory=list)

    @field_validator("items", mode="before")
    @classmethod
    def _items(cls, v):
        return [] if v is None else v


class RoleSuggestion(Lenient):
    _str_field = "title"
    title: str
    rationale: str = ""
    fit: str = "good"  # strong | good | stretch
    key_skills: list[str] = Field(default_factory=list)

    @field_validator("key_skills", mode="before")
    @classmethod
    def _lists(cls, v):
        return _str_list(v)


class RoleSuggestions(Lenient):
    roles: list[RoleSuggestion] = Field(default_factory=list)

    @field_validator("roles", mode="before")
    @classmethod
    def _roles(cls, v):
        return [] if v is None else v
