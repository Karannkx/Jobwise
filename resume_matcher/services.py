"""Application services: the single entry point used by the UI (and by tests).

Every public method opens its own short-lived database session, so it is safe to call
from background worker threads.
"""

from __future__ import annotations

import logging
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from . import scoring
from .ai import GeminiService
from .config import SettingsStore, data_dir
from .db import (
    AiCache,
    Candidate,
    CandidateSkill,
    Database,
    Job,
    MatchResult,
    Resume,
    SkillGapAnalysis,
    utc_now,
)
from .db.session import restrict_permissions
from .errors import (
    AIAuthError,
    AIError,
    AINotConfiguredError,
    NotFoundError,
    StorageError,
)
from .parsing import extract_text, file_sha256
from .jobsearch import HttpClient, all_providers
from .schemas import GapItem
from .search_mixin import SearchMixin

log = logging.getLogger(__name__)
Progress = Optional[Callable[[int, int, str], None]]


@dataclass
class ImportOutcome:
    file_name: str
    candidate_id: Optional[int] = None
    duplicate: bool = False
    error: Optional[str] = None


@dataclass
class RankRow:
    candidate: Candidate
    match: MatchResult

    @property
    def final_score(self) -> float:
        return self.match.final_score


def _fatal_ai(exc: Exception) -> bool:
    """Errors the user must fix (and that would fail every other request too)."""
    return isinstance(exc, (AINotConfiguredError, AIAuthError))


class Core(SearchMixin):
    def __init__(self, home: Optional[Path] = None, ai: Optional[GeminiService] = None, http: Optional[HttpClient] = None):
        self.home = Path(home) if home else data_dir()
        self.home.mkdir(parents=True, exist_ok=True)
        restrict_permissions(self.home)
        self.resume_dir = self.home / "resumes"
        self.resume_dir.mkdir(exist_ok=True)
        restrict_permissions(self.resume_dir)
        self.db = Database(self.home / "resume_matcher.db")
        self.settings = SettingsStore(self.db, self.home / "secret.json")
        self.ai = ai if ai is not None else GeminiService(self.settings, self.db)
        self.http = http if http is not None else HttpClient()
        self.providers = all_providers()

    # ================================================================ resumes
    def import_resume(self, path: Path | str) -> ImportOutcome:
        path = Path(path)
        text = extract_text(path)  # raises DocumentError subclasses
        digest = file_sha256(path)
        with self.db.session() as s:
            existing = s.scalars(select(Resume).where(Resume.file_hash == digest)).first()
            if existing:
                return ImportOutcome(path.name, existing.candidate_id, duplicate=True)

        parsed = self.ai.parse_resume(text)  # raises AIError
        profile = parsed.model_dump()

        years = parsed.total_experience_years
        if years <= 0:
            months = sum(e.duration_months or 0 for e in parsed.experience)
            years = round(months / 12.0, 1)
            profile["total_experience_years"] = years

        dest = self.resume_dir / f"{digest[:24]}{path.suffix.lower()}"
        try:
            shutil.copy2(path, dest)
            restrict_permissions(dest)
        except OSError as exc:
            raise StorageError(
                "The resume could not be saved to the application folder. Check disk space and permissions."
            ) from exc

        education = "; ".join(
            " ".join(p for p in (e.degree, e.field) if p) + (f" ({e.institution})" if e.institution else "")
            for e in parsed.education
            if e.degree or e.field
        )
        with self.db.session() as s:
            cand = Candidate(
                candidate_name=parsed.name or "Unknown",
                email=parsed.email,
                phone=parsed.phone,
                professional_summary=parsed.summary,
                total_experience=years,
                education=education or None,
                highest_education_level=scoring.highest_education(profile),
                profile_json=profile,
            )
            seen = set()
            for sk in parsed.skills:
                key = scoring.norm_skill(sk.name)
                if key and key not in seen:
                    seen.add(key)
                    cand.skills.append(
                        CandidateSkill(
                            skill_name=sk.name,
                            skill_category=sk.category,
                            proficiency_level=sk.proficiency,
                        )
                    )
            cand.resumes.append(
                Resume(
                    file_name=path.name,
                    file_path=str(dest),
                    parsed_content=text,
                    file_hash=digest,
                )
            )
            s.add(cand)
            s.flush()
            cid = cand.candidate_id
        log.info("resume imported (candidate_id=%s)", cid)
        return ImportOutcome(path.name, cid)

    def import_resumes(self, paths: list[Path | str], progress: Progress = None) -> list[ImportOutcome]:
        """Batch import with limited parallelism. Failures are reported per file."""
        paths = [Path(p) for p in paths]
        outcomes: dict[int, ImportOutcome] = {}
        total = len(paths)
        workers = min(self.settings.settings.batch_concurrency, max(1, total))
        fatal: list[Exception] = []

        def work(i: int, p: Path) -> ImportOutcome:
            if fatal:
                return ImportOutcome(p.name, error="Skipped after an earlier error.")
            try:
                return self.import_resume(p)
            except AIError as exc:
                if _fatal_ai(exc):
                    fatal.append(exc)
                return ImportOutcome(p.name, error=exc.user_message)
            except Exception as exc:
                user = getattr(exc, "user_message", None)
                if not user:
                    log.exception("unexpected resume import failure")
                return ImportOutcome(p.name, error=user or "Unexpected error while reading this file.")

        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(work, i, p): i for i, p in enumerate(paths)}
            for fut in as_completed(futures):
                outcomes[futures[fut]] = fut.result()
                done += 1
                if progress:
                    progress(done, total, paths[futures[fut]].name)
        return [outcomes[i] for i in range(total)]

    def list_candidates(self) -> list[Candidate]:
        with self.db.session() as s:
            rows = s.scalars(
                select(Candidate).options(selectinload(Candidate.skills)).order_by(Candidate.candidate_id.desc())
            ).all()
            return list(rows)

    def get_candidate(self, candidate_id: int) -> Candidate:
        with self.db.session() as s:
            cand = s.scalars(
                select(Candidate)
                .where(Candidate.candidate_id == candidate_id)
                .options(selectinload(Candidate.skills), selectinload(Candidate.resumes))
            ).first()
            if cand is None:
                raise NotFoundError("That candidate no longer exists.")
            return cand

    def delete_candidate(self, candidate_id: int) -> None:
        with self.db.session() as s:
            cand = s.get(Candidate, candidate_id)
            if cand is None:
                return
            files = [r.file_path for r in cand.resumes if r.file_path]
            s.delete(cand)
            # Cached parses contain the candidate's personal data: drop them too.
            s.execute(delete(AiCache).where(AiCache.kind == "parse_resume"))
        for f in files:
            self._remove_resume_file(f)

    def _remove_resume_file(self, file_path: str) -> None:
        p = Path(file_path)
        try:
            if p.resolve().parent == self.resume_dir.resolve():
                p.unlink(missing_ok=True)
        except OSError:
            log.warning("could not delete stored resume file")

    def save_preferences(
        self, candidate_id: int, roles: str = "", location: str = "", work_mode: str = ""
    ) -> None:
        with self.db.session() as s:
            cand = s.get(Candidate, candidate_id)
            if cand:
                cand.preferred_roles = roles.strip() or None
                cand.preferred_location = location.strip() or None
                cand.work_mode_pref = work_mode.strip().lower() or None

    # ==================================================================== jobs
    def import_job_text(self, text: str) -> int:
        text = (text or "").strip()
        if len(text) < 40:
            from .errors import EmptyDocumentError

            raise EmptyDocumentError("The job description is too short to analyse.")
        analysis = self.ai.analyze_job(text)
        data = analysis.model_dump()
        with self.db.session() as s:
            job = Job(
                job_title=analysis.title,
                company_name=analysis.company,
                job_description=text,
                required_skills=data["skills"],
                required_experience=analysis.required_experience_years,
                location=analysis.location,
                work_mode=analysis.work_mode,
                analysis_json=data,
            )
            s.add(job)
            s.flush()
            return job.job_id

    def import_job_file(self, path: Path | str) -> int:
        return self.import_job_text(extract_text(path))

    def list_jobs(self, limit: Optional[int] = None) -> list[Job]:
        with self.db.session() as s:
            q = select(Job).order_by(Job.job_id.desc())
            if limit:
                q = q.limit(limit)
            return list(s.scalars(q).all())

    def get_job(self, job_id: int) -> Job:
        with self.db.session() as s:
            job = s.get(Job, job_id)
            if job is None:
                raise NotFoundError("That job no longer exists.")
            return job

    def delete_job(self, job_id: int) -> None:
        with self.db.session() as s:
            job = s.get(Job, job_id)
            if job:
                s.delete(job)

    @staticmethod
    def _job_analysis(job: Job) -> dict[str, Any]:
        a = dict(job.analysis_json or {})
        a.setdefault("title", job.job_title)
        a.setdefault("skills", job.required_skills or [])
        a.setdefault("required_experience_years", job.required_experience)
        a.setdefault("location", job.location)
        a.setdefault("work_mode", job.work_mode)
        a.setdefault("certifications", [])
        a.setdefault("responsibilities", [])
        return a

    # ================================================================= matching
    @staticmethod
    def _profile_of(cand: Candidate) -> dict[str, Any]:
        profile = dict(cand.profile_json or {})
        profile.setdefault("skills", [{"name": s.skill_name} for s in cand.skills])
        profile.setdefault("total_experience_years", cand.total_experience or 0)
        return profile

    def _compute_match(
        self,
        cand: Candidate,
        profile: dict[str, Any],
        ja: dict[str, Any],
        assessment,
        ai_status: str = "ok",
        kind: str = "ai",
    ) -> dict[str, Any]:
        """Pure scoring step shared by full (AI) and quick (keyword-only) analyses."""
        weights = self.settings.settings.weights

        # validated skill equivalences suggested by the AI
        equivalences: dict[str, str] = {}
        if assessment:
            job_names = {scoring.norm_skill(s["name"]) for s in ja["skills"]}
            cand_names = {scoring.norm_skill(s.get("name", "")): s.get("name", "") for s in profile["skills"]}
            for eq in assessment.skill_equivalences:
                jn, cn = scoring.norm_skill(eq.job_skill), scoring.norm_skill(eq.candidate_skill)
                if jn in job_names and cn in cand_names:
                    equivalences[eq.job_skill] = cand_names[cn]

        cand_years = float(profile.get("total_experience_years") or 0)
        matches = scoring.match_skills(ja["skills"], profile, equivalences)
        s_score = scoring.skill_score(matches)
        e_score = scoring.experience_score(cand_years, ja.get("required_experience_years"))
        q_score = scoring.qualification_score(
            cand.highest_education_level or scoring.highest_education(profile),
            ja.get("required_education"),
            ja.get("certifications", []),
            profile.get("certifications", []),
        )
        sem = assessment.semantic_score if assessment else None
        overall, used, notes = scoring.combine(weights, s_score, e_score, q_score, sem)
        if kind == "quick":
            notes = [n for n in notes if "semantic" not in n.lower()]
            notes.append("Quick keyword-based score: the AI check has not been run for this job.")

        concerns = list(assessment.concerns) if assessment else []
        concerns += scoring.preference_concerns(ja, pref_mode=cand.work_mode_pref, pref_location=cand.preferred_location)
        if sem is not None:
            det, _, _ = scoring.combine(weights, s_score, e_score, q_score, None)
            if det and abs(sem - det) > 40:
                concerns.append(
                    "The AI's semantic assessment differs strongly from the structured score. "
                    "Review this candidate manually."
                )
        uncertainties = list(assessment.uncertainties) if assessment else []
        uncertainties += notes
        if not profile.get("skills"):
            uncertainties.append("No skills could be extracted from the resume.")
        if ai_status != "ok":
            uncertainties.append(f"AI analysis unavailable: {ai_status}")
        if ja.get("years_source") == "inferred from title":
            uncertainties.append("Required experience was inferred from the job title, not stated.")
        if ja.get("analysis_source") == "local" and kind == "quick" and not ja.get("skills"):
            uncertainties.append("No known skills were recognised in this posting; its score is unreliable.")

        n_req = len(matches)
        n_got = sum(1 for m in matches if m.status != "missing")
        strengths = list(assessment.strengths) if assessment else []
        if not strengths and n_req:
            strengths.append(f"Covers {n_got} of {n_req} listed skills.")
        explanation = (assessment.explanation if assessment and assessment.explanation else "") or (
            f"{'Keyword comparison' if kind == 'quick' else 'Structured comparison'} only: {n_got} of {n_req} listed skills were found"
            + (f"; {cand.total_experience:g} years of experience." if cand.total_experience else ".")
        )

        fit = scoring.experience_fit(cand_years, ja.get("required_experience_years"))
        pref_pen = scoring.preference_penalty(ja.get("work_mode"), ja.get("location"), cand.work_mode_pref, cand.preferred_location)
        fit_text = fit.text + (" (inferred from title)" if ja.get("years_source") == "inferred from title" else "")

        details = {
            "kind": kind,
            "skill_matches": [m.as_dict() for m in matches],
            "matched_skills": [m.skill for m in matches if m.status != "missing"],
            "missing_skills": [m.skill for m in matches if m.status == "missing"],
            "strengths": strengths,
            "concerns": concerns,
            "uncertainties": uncertainties,
            "ai_status": ai_status,
            "weights_used": used,
            "candidate_years": cand_years,
            "required_years": ja.get("required_experience_years"),
            "fit": {"label": fit.label, "text": fit_text, "penalty": round(fit.penalty + pref_pen, 1)},
        }
        return {
            "overall": overall, "skill": s_score, "experience": e_score, "qualification": q_score,
            "semantic": sem, "explanation": explanation, "details": details,
        }

    @staticmethod
    def _save_match(s, candidate_id: int, job_id: int, comp: dict[str, Any], kind: str) -> MatchResult:
        pair = (MatchResult.candidate_id == candidate_id, MatchResult.job_id == job_id)
        latest = s.scalars(select(MatchResult).where(*pair).order_by(MatchResult.match_id.desc())).first()
        if (
            kind == "ai" and latest and latest.analysis_kind == "ai"
            and (latest.overall_score, latest.skill_score, latest.experience_score,
                 latest.qualification_score, latest.semantic_score, latest.analysis_explanation)
            == (comp["overall"], comp["skill"], comp["experience"], comp["qualification"], comp["semantic"], comp["explanation"])
            and latest.details == comp["details"]
        ):
            return latest
        row = MatchResult(
            candidate_id=candidate_id, job_id=job_id, overall_score=comp["overall"], skill_score=comp["skill"],
            experience_score=comp["experience"], qualification_score=comp["qualification"],
            semantic_score=comp["semantic"], analysis_explanation=comp["explanation"], details=comp["details"],
            analysis_kind=kind,
        )
        if latest and latest.override_score is not None:  # keep the human decision
            row.override_score, row.override_note, row.reviewed_at = latest.override_score, latest.override_note, latest.reviewed_at
        if kind == "quick":
            s.execute(delete(MatchResult).where(*pair, MatchResult.analysis_kind == "quick"))
        s.add(row)
        s.flush()
        return row

    def match(self, candidate_id: int, job_id: int) -> MatchResult:
        """Full analysis: AI semantic assessment + deterministic scoring."""
        cand = self.get_candidate(candidate_id)
        job = self.get_job(job_id)
        profile = self._profile_of(cand)
        ja = self._job_analysis(job)

        assessment = None
        ai_status = "ok"
        try:
            assessment = self.ai.assess_match(profile, ja)
        except AIError as exc:
            if _fatal_ai(exc):
                raise
            ai_status = exc.user_message
            log.warning("AI assessment unavailable: %s", type(exc).__name__)

        comp = self._compute_match(cand, profile, ja, assessment, ai_status, "ai")
        with self.db.session() as s:
            return self._save_match(s, candidate_id, job_id, comp, "ai")

    def get_match(self, candidate_id: int, job_id: int) -> Optional[MatchResult]:
        with self.db.session() as s:
            return s.scalars(
                select(MatchResult)
                .where(MatchResult.candidate_id == candidate_id, MatchResult.job_id == job_id)
                .order_by(MatchResult.match_id.desc())
            ).first()

    def set_override(self, match_id: int, score: Optional[float], note: str = "") -> MatchResult:
        with self.db.session() as s:
            row = s.get(MatchResult, match_id)
            if row is None:
                raise NotFoundError("That analysis no longer exists.")
            if score is None:
                row.override_score, row.override_note, row.reviewed_at = None, None, None
            else:
                row.override_score = max(0.0, min(100.0, float(score)))
                row.override_note = note.strip() or None
                row.reviewed_at = utc_now()
            s.flush()
            return row

    # ================================================================== ranking
    def rank(
        self, job_id: int, candidate_ids: Optional[list[int]] = None, progress: Progress = None
    ) -> tuple[list[RankRow], list[tuple[str, str]]]:
        """Return (rows sorted best-first, failures[(candidate label, reason)])."""
        self.get_job(job_id)  # validates
        candidates = self.list_candidates()
        if candidate_ids is not None:
            wanted = set(candidate_ids)
            candidates = [c for c in candidates if c.candidate_id in wanted]
        total = len(candidates)
        rows: list[RankRow] = []
        failures: list[tuple[str, str]] = []
        fatal: list[Exception] = []
        workers = min(self.settings.settings.batch_concurrency, max(1, total))

        def work(c: Candidate):
            if fatal:
                raise fatal[0]
            return RankRow(c, self.match(c.candidate_id, job_id))

        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(work, c): c for c in candidates}
            for fut in as_completed(futures):
                c = futures[fut]
                done += 1
                try:
                    rows.append(fut.result())
                except Exception as exc:
                    if _fatal_ai(exc):
                        fatal.append(exc)
                    msg = getattr(exc, "user_message", None) or "Unexpected error."
                    if not hasattr(exc, "user_message"):
                        log.exception("ranking failure")
                    failures.append((f"{c.candidate_name or 'Candidate'} (#{c.candidate_id})", msg))
                if progress:
                    progress(done, total, f"{done}/{total}")
        if fatal:
            raise fatal[0]
        rows.sort(key=lambda r: (-r.final_score, -(r.match.skill_score or 0), r.candidate.candidate_id))
        return rows, failures

    def ranking_from_history(self, job_id: int) -> list[RankRow]:
        """Latest stored match per candidate for a job (no AI calls)."""
        with self.db.session() as s:
            sub = (
                select(func.max(MatchResult.match_id))
                .where(MatchResult.job_id == job_id)
                .group_by(MatchResult.candidate_id)
            )
            matches = s.scalars(select(MatchResult).where(MatchResult.match_id.in_(sub))).all()
            cands = {
                c.candidate_id: c
                for c in s.scalars(
                    select(Candidate).options(selectinload(Candidate.skills))
                ).all()
            }
            rows = [RankRow(cands[m.candidate_id], m) for m in matches if m.candidate_id in cands]
        rows.sort(key=lambda r: (-r.final_score, -(r.match.skill_score or 0), r.candidate.candidate_id))
        return rows

    # =============================================================== skill gaps
    def skill_gap(self, candidate_id: int, job_id: int) -> SkillGapAnalysis:
        match = self.match(candidate_id, job_id)
        cand = self.get_candidate(candidate_id)
        job = self.get_job(job_id)
        profile = dict(cand.profile_json or {})
        status = list((match.details or {}).get("skill_matches", []))
        missing = [m for m in status if m["status"] == "missing"]
        order = {"must_have": 0, "important": 1, "nice_to_have": 2}
        missing.sort(key=lambda m: order.get(m["importance"], 1))

        advice: dict[str, GapItem] = {}
        note = None
        if missing:
            try:
                result = self.ai.skill_gap_advice(
                    profile, [{"name": m["name"], "importance": m["importance"]} for m in missing], job.job_title
                )
                advice = {scoring.norm_skill(i.skill): i for i in result.items}
            except AIError as exc:
                if _fatal_ai(exc):
                    raise
                note = exc.user_message
        recs = []
        for m in missing:
            item = advice.get(scoring.norm_skill(m["name"]))
            recs.append(
                {
                    "skill": m["name"],
                    "importance": m["importance"],
                    "difficulty": item.difficulty if item else None,
                    "estimated_weeks": item.estimated_weeks if item else None,
                    "learning_path": item.learning_path if item else [],
                    "certifications": item.certifications if item else [],
                    "projects": item.projects if item else [],
                    "note": None if item else (note or "No suggestion was generated for this skill."),
                }
            )
        with self.db.session() as s:
            row = SkillGapAnalysis(
                candidate_id=candidate_id,
                job_id=job_id,
                skill_status=status,
                missing_skills=[{"name": m["name"], "importance": m["importance"]} for m in missing],
                recommendations=recs,
            )
            s.add(row)
            s.flush()
            return row

    # ============================================================ role ideas
    def suggest_roles(self, candidate_id: int, prefs: dict[str, str]):
        cand = self.get_candidate(candidate_id)
        profile = dict(cand.profile_json or {})
        return self.ai.suggest_roles(profile, {k: v for k, v in prefs.items() if v})

    # ================================================================= overviews
    def _latest_matches(self, s) -> list[MatchResult]:
        sub = select(func.max(MatchResult.match_id)).group_by(
            MatchResult.candidate_id, MatchResult.job_id
        )
        return list(s.scalars(select(MatchResult).where(MatchResult.match_id.in_(sub))).all())

    def dashboard(self) -> dict[str, Any]:
        with self.db.session() as s:
            n_cand = s.scalar(select(func.count()).select_from(Candidate)) or 0
            n_jobs = s.scalar(select(func.count()).select_from(Job)) or 0
            latest = self._latest_matches(s)
            ai_latest = [m for m in latest if m.analysis_kind == "ai"]
            avg = round(sum(m.final_score for m in ai_latest) / len(ai_latest), 1) if ai_latest else None
            names = {c.candidate_id: c.candidate_name for c in s.scalars(select(Candidate)).all()}
            titles = {j.job_id: j.job_title for j in s.scalars(select(Job)).all()}
            top = sorted(latest, key=lambda m: -m.final_score)[:6]
            recent = s.scalars(
                select(MatchResult).where(MatchResult.analysis_kind == "ai").order_by(MatchResult.match_id.desc()).limit(8)
            ).all()

            def row(m: MatchResult) -> dict[str, Any]:
                return {
                    "candidate": names.get(m.candidate_id, "?"),
                    "job": titles.get(m.job_id, "?"),
                    "score": m.final_score,
                    "when": m.created_at,
                    "candidate_id": m.candidate_id,
                    "job_id": m.job_id,
                }

            return {
                "resumes": n_cand,
                "jobs": n_jobs,
                "avg_score": avg,
                "matches": len(ai_latest),
                "top": [row(m) for m in top],
                "recent": [row(m) for m in recent],
            }

    def history(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.session() as s:
            names = {c.candidate_id: c.candidate_name for c in s.scalars(select(Candidate)).all()}
            titles = {j.job_id: j.job_title for j in s.scalars(select(Job)).all()}
            rows = s.scalars(
                select(MatchResult).where(MatchResult.analysis_kind == "ai").order_by(MatchResult.match_id.desc()).limit(limit)
            ).all()
            return [
                {
                    "match_id": m.match_id,
                    "candidate_id": m.candidate_id,
                    "job_id": m.job_id,
                    "candidate": names.get(m.candidate_id, "?"),
                    "job": titles.get(m.job_id, "?"),
                    "score": m.final_score,
                    "when": m.created_at,
                }
                for m in rows
            ]

    # ================================================================ data admin
    def clear_ai_cache(self) -> int:
        return self.ai.clear_cache()

    def delete_all_data(self) -> None:
        with self.db.session() as s:
            s.execute(delete(MatchResult))
            s.execute(delete(SkillGapAnalysis))
            s.execute(delete(CandidateSkill))
            s.execute(delete(Resume))
            s.execute(delete(Candidate))
            s.execute(delete(Job))
            s.execute(delete(AiCache))
        for f in self.resume_dir.glob("*"):
            try:
                f.unlink()
            except OSError:
                log.warning("could not remove a stored resume file")

    def close(self) -> None:
        self.http.close()
        self.db.dispose()
