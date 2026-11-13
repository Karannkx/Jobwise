from datetime import timedelta

import pytest

from resume_matcher.db import utc_now
from resume_matcher.errors import AppError
from resume_matcher.jobsearch import CredField, Posting, Provider, ProviderError

DESC_GOOD = "Remote role. Required: Python, SQL, Docker, AWS. 3+ years experience. Bachelor degree."
DESC_BAD = "On site in Pune. Required: COBOL, Fortran, Excel. 12+ years experience."


class FakeProvider(Provider):
    def __init__(self, pid, postings=None, error=None, key=False, cache_minutes=30):
        self.id, self.label = pid, pid.title()
        self.fields = (CredField("key", "API key", f"FAKE_{pid.upper()}_KEY"),) if key else ()
        self.cache_minutes = cache_minutes
        self._postings, self._error, self.calls = postings or [], error, 0

    def fetch(self, http, q, creds):
        self.calls += 1
        if self._error:
            raise ProviderError(self._error)
        return list(self._postings)


def P(src, ext, title, company, desc, **kw):
    return Posting(source=src, external_id=ext, title=title, url=f"https://x.test/{src}/{ext}",
                   company=company, description=desc, posted_at=kw.pop("posted_at", utc_now() - timedelta(days=2)), **kw)


@pytest.fixture()
def alice(core, sample_files):
    out = core.import_resumes([sample_files[0]])
    return out[0].candidate_id


def test_search_ranks_dedupes_and_isolates_failures(core, alice):
    good = P("a", "1", "Data Engineer", "Acme", DESC_GOOD, remote=True)
    dup = P("b", "9", "Data Engineer", "ACME", DESC_GOOD + " Extra detail.", remote=True)
    bad = P("a", "2", "Data Engineer II", "Oldco", DESC_BAD)
    stale = P("a", "3", "Data Engineer", "Ancient", DESC_GOOD, posted_at=utc_now() - timedelta(days=400))
    pa, pb = FakeProvider("a", [good, bad, stale]), FakeProvider("b", [dup])
    pc, pd = FakeProvider("c", error="Service down."), FakeProvider("d", key=True)
    core.providers = [pa, pb, pc, pd]
    out = core.search_jobs(alice, roles="data engineer")
    assert out.found == 2  # dup merged, stale dropped
    assert out.results[0].job.job_title == "Data Engineer"
    assert out.results[0].adjusted > out.results[1].adjusted
    assert out.results[0].job.also_on  # remembers the other source
    st = {s.id: s for s in out.sources}
    assert st["c"].error and st["d"].skipped == "API key needed" and st["a"].count == 3
    assert [r.rank for r in out.results] == [1, 2]


def test_cache_prevents_second_call(core, alice):
    pa = FakeProvider("a", [P("a", "1", "Data Engineer", "Acme", DESC_GOOD)])
    core.providers = [pa]
    core.search_jobs(alice, roles="data engineer")
    out = core.search_jobs(alice, roles="data engineer")
    assert pa.calls == 1 and out.sources[0].cached


def test_disabled_source_is_skipped(core, alice):
    pa = FakeProvider("a", [P("a", "1", "Data Engineer", "Acme", DESC_GOOD)])
    core.providers = [pa]
    core.settings.update(disabled_sources=["a"])
    out = core.search_jobs(alice, roles="data engineer")
    assert pa.calls == 0 and out.sources[0].skipped == "Turned off" and out.results == []


def test_ai_verifies_top_jobs_and_persists(core, alice):
    core.providers = [FakeProvider("a", [P("a", "1", "Data Engineer", "Acme", DESC_GOOD), P("a", "2", "Data Engineer", "Zed", DESC_BAD)])]
    core.settings.update(ai_verify_top=1)
    out = core.search_jobs(alice, roles="data engineer")
    assert sum(r.verified for r in out.results) == 1 and out.results[0].verified
    again = core.latest_job_results(alice)
    assert [r.job.job_id for r in again] == [r.job.job_id for r in out.results]
    assert core.clear_found_jobs() == 2 and core.latest_job_results(alice) == []


def test_no_ai_key_still_gives_quick_scores(core, alice):
    core.ai.is_configured = lambda: False
    core.providers = [FakeProvider("a", [P("a", "1", "Data Engineer", "Acme", DESC_GOOD)])]
    out = core.search_jobs(alice, roles="data engineer")
    assert out.results and not out.results[0].verified and out.ai_note and 0 < out.results[0].adjusted <= 100


def test_nothing_to_search(core, alice, monkeypatch):
    monkeypatch.setattr("resume_matcher.search_mixin.build_queries", lambda *a, **k: [])
    with pytest.raises(AppError):
        core.search_jobs(alice, roles="")
