"""SQLAlchemy models for the local SQLite database."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Candidate(Base):
    __tablename__ = "candidates"

    candidate_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_name: Mapped[str] = mapped_column(String(200), default="Unknown")
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    professional_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_experience: Mapped[float] = mapped_column(Float, default=0.0)
    education: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Extras beyond the PRD's minimum columns
    highest_education_level: Mapped[int] = mapped_column(Integer, default=0)
    profile_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    preferred_roles: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    preferred_location: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    work_mode_pref: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    skills: Mapped[list["CandidateSkill"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", passive_deletes=True
    )
    resumes: Mapped[list["Resume"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", passive_deletes=True
    )


class CandidateSkill(Base):
    __tablename__ = "candidate_skills"
    __table_args__ = (
        Index("ix_candidate_skills_candidate", "candidate_id"),
        Index("ix_candidate_skills_name", "skill_name"),
    )

    skill_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.candidate_id", ondelete="CASCADE")
    )
    skill_name: Mapped[str] = mapped_column(String(200))
    skill_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    proficiency_level: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    candidate: Mapped[Candidate] = relationship(back_populates="skills")


class Resume(Base):
    __tablename__ = "resumes"
    __table_args__ = (
        Index("ix_resumes_candidate", "candidate_id"),
        Index("ix_resumes_hash", "file_hash"),
    )

    resume_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.candidate_id", ondelete="CASCADE")
    )
    file_name: Mapped[str] = mapped_column(String(300))
    file_path: Mapped[Optional[str]] = mapped_column(String(600), nullable=True)
    parsed_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    upload_date: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    candidate: Mapped[Candidate] = relationship(back_populates="resumes")


class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_title: Mapped[str] = mapped_column(String(300))
    company_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    job_description: Mapped[str] = mapped_column(Text)
    # list of {"name": str, "importance": "must_have"|"important"|"nice_to_have"}
    required_skills: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    required_experience: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    work_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    analysis_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # Job-search fields (NULL for jobs that were not found through a search provider)
    source: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(1200), nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    salary: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    employment_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    also_on: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (Index("ix_jobs_source_ext", "source", "external_id", unique=True),)


class MatchResult(Base):
    __tablename__ = "match_results"
    __table_args__ = (Index("ix_match_pair", "candidate_id", "job_id"), Index("ix_match_job", "job_id"))

    match_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.candidate_id", ondelete="CASCADE")
    )
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"))
    overall_score: Mapped[float] = mapped_column(Float)
    skill_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    experience_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    qualification_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    semantic_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    analysis_explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # matched/missing skills, strengths, concerns, uncertainties, AI status
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # Recruiter review (human-in-the-loop)
    override_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    override_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # "ai" = full AI-assisted analysis, "quick" = keyword-only score used to pre-rank search results
    analysis_kind: Mapped[str] = mapped_column(String(10), default="ai", server_default="ai")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    @property
    def final_score(self) -> float:
        return self.override_score if self.override_score is not None else self.overall_score


class SkillGapAnalysis(Base):
    __tablename__ = "skill_gap_analysis"
    __table_args__ = (Index("ix_gap_pair", "candidate_id", "job_id"),)

    gap_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.candidate_id", ondelete="CASCADE")
    )
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"))
    # [{"name", "importance", "status"}] for every required skill
    skill_status: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    missing_skills: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    recommendations: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class AiCache(Base):
    """Reusable AI responses, keyed by a hash of (task, model, prompt)."""

    __tablename__ = "ai_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    response: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
