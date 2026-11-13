"""Job-search pipeline (mixed into ``Core``).

1. Build queries from the candidate (explicit roles, else recent job titles / top skills).
2. Fetch from every enabled source in parallel; failures are isolated and reported per source.
3. De-duplicate (same source id, or same title + company across sources) and drop stale listings.
4. Store the postings and score ALL of them locally and instantly (no AI needed).
5. Re-analyse the best few with Gemini (fuller job analysis + semantic fit) when a key is configured.
6. Order by *fit-adjusted* score: the weighted match score minus small penalties for roles far above
   or far below the candidate's experience, or that conflict with stated work-mode / location.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Optional

from sqlalchemy import delete, func, select

from . import scoring
from .db import AiCache, Job, MatchResult, utc_now
from .errors import AIError, AINotConfiguredError, AppError
from .jobsearch import (
    Posting, Provider, ProviderError, SearchQuery, SkillExtractor, analyse_posting, build_queries, is_relevant,
    level_from_years,
)

log = logging.getLogger(__name__)
Progress = Optional[Callable[[int, int, str], None]]


@dataclass
class SourceStatus:
    id: str
    label: str
    count: int = 0
    error: Optional[str] = None
    skipped: Optional[str] = None  # "Turned off" | "API key needed"
    cached: bool = False


@dataclass
class JobResult:
    job: Job
    match: MatchResult
    fit_label: str = "unknown"
    fit_text: str = ""
    penalty: float = 0.0
    adjusted: float = 0.0
    verified: bool = False
    top_pick: bool = False
    rank: int = 0


@dataclass
class SearchOutcome:
    results: list[JobResult]
    sources: list[SourceStatus]
    queries: list[str]
    found: int = 0
    ai_note: Optional[str] = None


def _norm_key(title: str, company: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "", f"{title}|{company or ''}".lower())


def _is_remote_posting(p: Posting) -> bool:
    return bool(p.remote) or bool(re.search(r"\bremote\b|work from home|anywhere", f"{p.title} {p.location or ''}", re.I))


class SearchMixin:
    # ---------------------------------------------------------------- credentials / state
    def provider_credentials(self, p: Provider) -> dict[str, str]:
        return {f.id: self.settings.get_credential(p.id, f.id, f.env) for f in p.fields}

    def provider_state(self, p: Provider) -> str:
        """'disabled' | 'needs_key' | 'ready'"""
        if p.id in self.settings.settings.disabled_sources:
            return "disabled"
        return "needs_key" if p.missing(self.provider_credentials(p)) else "ready"

    # ---------------------------------------------------------------- fetching
    def _cached_fetch(self, p: Provider, q: SearchQuery, creds: dict[str, str]) -> tuple[list[Posting], bool]:
        key = hashlib.sha256(f"jobs\0{p.id}\0{p.cache_key(q)}".encode()).hexdigest()
        try:
            with self.db.session() as s:
                row = s.get(AiCache, key)
                if row and utc_now() - row.created_at < timedelta(minutes=p.cache_minutes):
                    return [Posting.from_dict(d) for d in json.loads(row.response)], True
        except Exception:
            log.debug("job cache read failed", exc_info=True)
        postings = p.fetch(self.http, q, creds)
        try:
            with self.db.session() as s:
                s.merge(AiCache(cache_key=key, kind=f"jobs:{p.id}", response=json.dumps([x.to_dict() for x in postings]), created_at=utc_now()))
        except Exception:
            log.debug("job cache write failed", exc_info=True)
        return postings, False

    def _fetch_all(self, q: SearchQuery, progress: Progress) -> tuple[list[Posting], list[SourceStatus]]:
        disabled = set(self.settings.settings.disabled_sources)
        statuses: dict[str, SourceStatus] = {}
        queue: list[tuple[Provider, dict[str, str]]] = []
        for p in self.providers:
            st = SourceStatus(p.id, p.label)
            statuses[p.id] = st
            if p.id in disabled:
                st.skipped = "Turned off"
                continue
            creds = self.provider_credentials(p)
            if p.missing(creds):
                st.skipped = "API key needed"
                continue
            queue.append((p, creds))

        def work(item: tuple[Provider, dict[str, str]]):
            p, creds = item
            postings, cached = self._cached_fetch(p, q, creds)
            if p.feed:
                postings = [x for x in postings if is_relevant(x, q.keywords)]
            return p, postings, cached

        out: list[Posting] = []
        done = 0
        if queue:
            with ThreadPoolExecutor(max_workers=min(8, len(queue))) as pool:
                futures = {pool.submit(work, item): item[0] for item in queue}
                for fut in as_completed(futures):
                    p = futures[fut]
                    st = statuses[p.id]
                    try:
                        _p, postings, cached = fut.result()
                        st.count, st.cached = len(postings), cached
                        out.extend(postings)
                    except AppError as exc:
                        st.error = exc.user_message
                    except Exception:
                        log.exception("job source failed: %s", p.id)
                        st.error = f"{p.label} failed unexpectedly."
                    done += 1
                    if progress:
                        progress(done, len(queue), f"Searched {p.label}")
        return out, [statuses[p.id] for p in self.providers]

    # ---------------------------------------------------------------- main entry
    def search_jobs(
        self,
        candidate_id: int,
        roles: str = "",
        location: str = "",
        work_mode: str = "",
        progress: Progress = None,
        verify: bool = True,
    ) -> SearchOutcome:
        cand = self.get_candidate(candidate_id)
        profile = self._profile_of(cand)
        st = self.settings.settings
        self.save_preferences(candidate_id, roles, location, work_mode)

        queries = build_queries(profile, roles)
        if not queries:
            raise AppError("There is nothing to search for yet. Enter a preferred role, or import a resume that lists work experience or skills.")
        cand_years = float(profile.get("total_experience_years") or 0)
        q = SearchQuery(
            keywords=queries, location=location.strip(), remote_only=(work_mode == "remote"),
            country=st.search_country, limit=st.per_source_limit, max_age_days=st.max_job_age_days,
            level=level_from_years(cand_years),
        )

        # 1) fetch
        raw, sources = self._fetch_all(q, progress)
        postings = self._clean_postings(raw, q)

        # 2) store + quick-score everything
        if progress:
            progress(0, 0, f"Scoring {len(postings)} jobs")
        extractor = SkillExtractor(s.get("name", "") for s in profile.get("skills", []))
        job_ids = self._upsert_postings(postings, extractor)
        results = self._quick_score(cand, profile, job_ids)

        # 3) AI verification of the best few
        ai_note = None
        if verify and st.ai_verify_top > 0 and results:
            results, ai_note = self._verify_top(cand, profile, results, st.ai_verify_top, progress)
        elif verify and not self.ai.is_configured():
            ai_note = "Add a Gemini API key in Settings to AI-verify the best matches. Scores shown are keyword-based."

        results = self._rank_results(results)
        return SearchOutcome(results, sources, queries, found=len(postings), ai_note=ai_note)

    # ---------------------------------------------------------------- helpers
    def _clean_postings(self, raw: list[Posting], q: SearchQuery) -> list[Posting]:
        cutoff = utc_now() - timedelta(days=q.max_age_days)
        kept: dict[tuple[str, str], Posting] = {}
        for p in raw:
            if not (p.title and p.url and p.external_id):
                continue
            if p.posted_at and p.posted_at < cutoff:
                continue
            if q.remote_only and not _is_remote_posting(p):
                continue
            kept.setdefault(p.key, p)

        # same job listed on several sources -> keep the richest one, remember the others
        groups: dict[str, list[Posting]] = {}
        for p in kept.values():
            groups.setdefault(_norm_key(p.title, p.company), []).append(p)
        out: list[Posting] = []
        for group in groups.values():
            group.sort(key=lambda x: len(x.description), reverse=True)
            best = group[0]
            best.also_on = sorted({g.source for g in group[1:] if g.source != best.source})
            out.append(best)
        return out

    def _upsert_postings(self, postings: list[Posting], extractor: SkillExtractor) -> list[int]:
        ids: list[int] = []
        now = utc_now()
        with self.db.session() as s:
            existing = {(j.source, j.external_id): j for j in s.scalars(select(Job).where(Job.source.isnot(None))).all()}
            for p in postings:
                analysis = analyse_posting(p, extractor)
                job = existing.get(p.key)
                if job is None:
                    job = Job(source=p.source, external_id=p.external_id, job_title="", job_description="")
                    s.add(job)
                job.job_title = p.title
                job.company_name = p.company
                job.job_description = p.description or job.job_description or p.title
                job.location = p.location
                job.url = p.url
                job.posted_at = p.posted_at
                job.salary = p.salary
                job.employment_type = p.employment_type
                job.also_on = p.also_on
                job.last_seen = now
                job.work_mode = analysis["work_mode"]
                old = job.analysis_json or {}
                if old.get("analysis_source") == "ai":  # never replace a better AI analysis with keywords
                    analysis = {**old, "work_mode": old.get("work_mode") or analysis["work_mode"]}
                job.analysis_json = analysis
                job.required_skills = analysis["skills"]
                job.required_experience = analysis["required_experience_years"]
                s.flush()
                ids.append(job.job_id)
        return ids

    def _quick_score(self, cand, profile: dict[str, Any], job_ids: list[int]) -> list[JobResult]:
        results: list[JobResult] = []
        with self.db.session() as s:
            jobs = {j.job_id: j for j in s.scalars(select(Job).where(Job.job_id.in_(job_ids))).all()} if job_ids else {}
            latest_ai: dict[int, MatchResult] = {}
            if job_ids:
                for m in s.scalars(
                    select(MatchResult)
                    .where(MatchResult.candidate_id == cand.candidate_id, MatchResult.job_id.in_(job_ids), MatchResult.analysis_kind == "ai")
                    .order_by(MatchResult.match_id.asc())
                ):
                    latest_ai[m.job_id] = m
            for jid in job_ids:
                job = jobs[jid]
                if jid in latest_ai:  # an earlier AI analysis is better than a keyword score
                    results.append(self._to_result(job, latest_ai[jid]))
                    continue
                comp = self._compute_match(cand, profile, self._job_analysis(job), None, "ok", "quick")
                results.append(self._to_result(job, self._save_match(s, cand.candidate_id, jid, comp, "quick")))
        return results

    @staticmethod
    def _to_result(job: Job, m: MatchResult) -> JobResult:
        fit = (m.details or {}).get("fit") or {}
        penalty = float(fit.get("penalty", 0.0))
        adjusted = m.override_score if m.override_score is not None else max(0.0, m.overall_score - penalty)
        return JobResult(
            job=job, match=m, fit_label=fit.get("label", "unknown"), fit_text=fit.get("text", ""),
            penalty=penalty, adjusted=round(adjusted, 1), verified=(m.analysis_kind == "ai"),
        )

    @staticmethod
    def _rank_results(results: list[JobResult]) -> list[JobResult]:
        def newest(r: JobResult) -> float:
            return r.job.posted_at.timestamp() if r.job.posted_at else 0.0

        results.sort(key=lambda r: (-r.adjusted, -(r.match.skill_score or 0.0), -newest(r)))
        for i, r in enumerate(results, 1):
            r.rank = i
            r.top_pick = i <= 3 and r.adjusted >= 50 and r.fit_label != "reach"
        return results

    def _verify_top(self, cand, profile, results: list[JobResult], n: int, progress: Progress):
        if not self.ai.is_configured():
            return results, "Add a Gemini API key in Settings to AI-verify the best matches. Scores shown are keyword-based."
        pending = [r for r in self._rank_results(list(results)) if not r.verified][:n]
        if not pending:
            return results, None
        by_id = {r.job.job_id: r for r in results}
        fatal: list[Exception] = []
        done = ok = 0

        def work(r: JobResult) -> JobResult:
            if fatal:
                raise fatal[0]
            m, job = self._verify_job(cand.candidate_id, r.job.job_id)
            return self._to_result(job, m)

        with ThreadPoolExecutor(max_workers=self.settings.settings.batch_concurrency) as pool:
            futures = {pool.submit(work, r): r for r in pending}
            for fut in as_completed(futures):
                r = futures[fut]
                done += 1
                try:
                    by_id[r.job.job_id] = fut.result()
                    ok += 1
                except AIError as exc:
                    if isinstance(exc, AINotConfiguredError) or type(exc).__name__ == "AIAuthError":
                        fatal.append(exc)
                except Exception:
                    log.exception("AI verification failed for one job")
                if progress:
                    progress(done, len(pending), "AI check")
        note = f"AI verified the top {ok} of {len(pending)} matches." if ok == len(pending) else (
            f"AI verified {ok} of {len(pending)} top matches; the rest keep keyword-based scores." if ok else
            ("The AI check could not run" + (f": {fatal[0].user_message}" if fatal else ".") + " Scores shown are keyword-based.")
        )
        return list(by_id.values()), note

    def _verify_job(self, candidate_id: int, job_id: int) -> tuple[MatchResult, Job]:
        job = self.get_job(job_id)
        if (job.analysis_json or {}).get("analysis_source") != "ai":
            header = "\n".join(x for x in (job.job_title, job.company_name, job.location) if x)
            analysis = self.ai.analyze_job(f"{header}\n\n{job.job_description}")
            data = analysis.model_dump()
            data["analysis_source"] = "ai"
            data["work_mode"] = data.get("work_mode") or job.work_mode
            data["location"] = data.get("location") or job.location
            with self.db.session() as s:
                j = s.get(Job, job_id)
                j.analysis_json = data
                j.required_skills = data["skills"]
                j.required_experience = data["required_experience_years"]
                if data["work_mode"]:
                    j.work_mode = data["work_mode"]
        m = self.match(candidate_id, job_id)
        return m, self.get_job(job_id)

    # ---------------------------------------------------------------- persistence
    def latest_job_results(self, candidate_id: int, limit: int = 300) -> list[JobResult]:
        """Previously found jobs with the newest analysis for this candidate (survives restarts)."""
        with self.db.session() as s:
            sub = (
                select(func.max(MatchResult.match_id))
                .where(MatchResult.candidate_id == candidate_id)
                .group_by(MatchResult.job_id)
            )
            matches = {m.job_id: m for m in s.scalars(select(MatchResult).where(MatchResult.match_id.in_(sub))).all()}
            if not matches:
                return []
            jobs = s.scalars(select(Job).where(Job.job_id.in_(list(matches)), Job.source.isnot(None))).all()
            results = [self._to_result(j, matches[j.job_id]) for j in jobs]
        return self._rank_results(results)[:limit]

    def clear_found_jobs(self) -> int:
        """Delete every job that came from a search (and, via cascade, its analyses)."""
        with self.db.session() as s:
            n = s.execute(delete(Job).where(Job.source.isnot(None))).rowcount or 0
            s.execute(delete(AiCache).where(AiCache.kind.like("jobs:%")))
        return n

    def analyse_job_for(self, candidate_id: int, job_id: int) -> JobResult:
        """On-demand full AI analysis of one found job."""
        m, job = self._verify_job(candidate_id, job_id)
        return self._to_result(job, m)
