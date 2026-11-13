"""Types shared by all job-search providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from ..errors import AppError


class ProviderError(AppError):
    """A job source failed. The message is safe to show and never contains URLs or keys."""


@dataclass(frozen=True)
class CredField:
    id: str
    label: str
    env: str  # environment variable that can supply the value
    secret: bool = True
    optional: bool = False


@dataclass
class SearchQuery:
    keywords: list[str]  # role titles / skill phrases, best first
    location: str = ""
    remote_only: bool = False
    country: str = "in"  # ISO 3166-1 alpha-2 (lower case)
    limit: int = 40
    max_age_days: int = 45
    level: Optional[str] = None  # "entry" | "mid" | "senior" | None (derived from candidate experience)

    def primary(self) -> str:
        return self.keywords[0] if self.keywords else ""


@dataclass
class Posting:
    source: str
    external_id: str
    title: str
    url: str
    company: Optional[str] = None
    location: Optional[str] = None
    remote: Optional[bool] = None  # None = unknown
    description: str = ""
    posted_at: Optional[datetime] = None
    salary: Optional[str] = None
    employment_type: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    also_on: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.external_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "external_id": self.external_id, "title": self.title, "url": self.url,
            "company": self.company, "location": self.location, "remote": self.remote,
            "description": self.description,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "salary": self.salary, "employment_type": self.employment_type, "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Posting":
        pa = d.get("posted_at")
        return cls(
            source=d["source"], external_id=d["external_id"], title=d["title"], url=d["url"],
            company=d.get("company"), location=d.get("location"), remote=d.get("remote"),
            description=d.get("description", ""),
            posted_at=datetime.fromisoformat(pa) if pa else None,
            salary=d.get("salary"), employment_type=d.get("employment_type"), tags=list(d.get("tags", [])),
        )
