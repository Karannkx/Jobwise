import csv

import pytest

from conftest import JOB_TEXT
from resume_matcher import reports
from resume_matcher.errors import AIAuthError, EmptyDocumentError, NotFoundError
from resume_matcher.db import AiCache, Resume


def _setup(core, sample_files):
    a, b = sample_files
    out = core.import_resumes([a, b])
    assert all(o.error is None for o in out), [o.error for o in out]
    job_id = core.import_job_text(JOB_TEXT)
    return [o.candidate_id for o in out], job_id


def test_import_and_persist(core, sample_files, tmp_path):
    (alice_id, bob_id), _ = _setup(core, sample_files)
    cand = core.get_candidate(alice_id)
    assert cand.candidate_name == "Alice Example"
    assert cand.total_experience == 5
    assert {s.skill_name for s in cand.skills} >= {"Python", "Docker", "PostgreSQL"}
    # data persists after "restart": reopen the same home folder
    from resume_matcher.services import Core

    core2 = Core(home=core.home)
    assert len(core2.list_candidates()) == 2
    core2.close()


def test_duplicate_resume_is_not_reparsed(core, sample_files):
    a, _ = sample_files
    first = core.import_resume(a)
    calls = core.ai.calls.count("parse_resume")
    second = core.import_resume(a)
    assert second.duplicate and second.candidate_id == first.candidate_id
    assert core.ai.calls.count("parse_resume") == calls


def test_match_scores_and_explanations(core, sample_files):
    (alice, bob), job = _setup(core, sample_files)
    m = core.match(alice, job)
    d = m.details
    assert "Python" in d["matched_skills"]
    assert "SQL" in d["matched_skills"]  # via validated AI equivalence (PostgreSQL)
    assert set(d["missing_skills"]) == {"AWS", "Kubernetes"} or "Kubernetes" in d["missing_skills"]
    assert 0 <= m.overall_score <= 100
    assert m.analysis_explanation
    mb = core.match(bob, job)
    assert m.overall_score > mb.overall_score


def test_ranking_orders_best_first_and_is_name_blind_on_ties(core, sample_files):
    (alice, bob), job = _setup(core, sample_files)
    rows, failures = core.rank(job)
    assert not failures
    assert [r.candidate.candidate_id for r in rows] == [alice, bob]
    again = core.ranking_from_history(job)
    assert [r.candidate.candidate_id for r in again] == [alice, bob]


def test_override_survives_rematch_and_changes_rank(core, sample_files):
    (alice, bob), job = _setup(core, sample_files)
    core.rank(job)
    mb = core.get_match(bob, job)
    core.set_override(mb.match_id, 99, "Strong portfolio reviewed manually")
    rows, _ = core.rank(job)
    assert rows[0].candidate.candidate_id == bob
    assert rows[0].match.override_note.startswith("Strong")
    core.set_override(mb.match_id, None)
    rows, _ = core.rank(job)
    assert rows[0].candidate.candidate_id == alice


def test_weights_are_configurable(core, sample_files):
    (alice, _), job = _setup(core, sample_files)
    base = core.match(alice, job).overall_score
    core.settings.update(weights={"skills": 0.0, "experience": 0.0, "qualification": 0.0, "semantic": 1.0})
    assert core.match(alice, job).overall_score == 70.0
    assert base != 70.0


def test_skill_gap_with_recommendations(core, sample_files):
    (alice, _), job = _setup(core, sample_files)
    gap = core.skill_gap(alice, job)
    names = [m["name"] for m in gap.missing_skills]
    assert "Kubernetes" in names
    rec = next(r for r in gap.recommendations if r["skill"] == "Kubernetes")
    assert rec["learning_path"] and rec["difficulty"] == "moderate"


def test_suggest_roles(core, sample_files):
    (alice, _), job = _setup(core, sample_files)
    roles = core.suggest_roles(alice, {"work_mode": "remote"})
    assert roles.roles[0].title == "Data Engineer"


def test_soft_ai_failure_still_gives_structured_score(core, sample_files):
    from resume_matcher.errors import AINetworkError
    from resume_matcher.ai.gemini import _Retryable

    (alice, _), job = _setup(core, sample_files)
    core.settings.update(max_retries=0)
    core.ai.responses = [_Retryable(AINetworkError("offline"))]
    core.ai._cache_get = lambda *a, **k: None  # force a real call
    m = core.match(alice, job)
    assert m.semantic_score is None
    assert m.details["ai_status"] != "ok"
    assert any("unavailable" in u.lower() for u in m.details["uncertainties"])
    assert m.overall_score > 0


def test_auth_failure_is_raised(core, sample_files):
    (alice, _), job = _setup(core, sample_files)
    core.settings.update(weights={"skills": 1, "experience": 0, "qualification": 0, "semantic": 0})
    core.ai._cache_get = lambda *a, **k: None
    core.ai.responses = [AIAuthError("bad key")]
    with pytest.raises(AIAuthError):
        core.match(alice, job)


def test_delete_candidate_removes_everything(core, sample_files):
    (alice, bob), job = _setup(core, sample_files)
    core.rank(job)
    stored = [r.file_path for r in core.get_candidate(alice).resumes]
    core.delete_candidate(alice)
    with pytest.raises(NotFoundError):
        core.get_candidate(alice)
    import os

    assert not any(os.path.exists(p) for p in stored)
    assert core.get_match(alice, job) is None
    with core.db.session() as s:
        assert s.query(Resume).count() == 1
        assert s.query(AiCache).filter(AiCache.kind == "parse_resume").count() == 0


def test_delete_all_and_job_delete(core, sample_files):
    _, job = _setup(core, sample_files)
    core.delete_job(job)
    assert core.list_jobs() == []
    core.delete_all_data()
    assert core.list_candidates() == []
    assert not list(core.resume_dir.glob("*"))


def test_short_job_description_rejected(core):
    with pytest.raises(EmptyDocumentError):
        core.import_job_text("too short")


def test_dashboard_numbers(core, sample_files):
    _, job = _setup(core, sample_files)
    core.rank(job)
    d = core.dashboard()
    assert d["resumes"] == 2 and d["jobs"] == 1 and d["matches"] == 2
    assert d["avg_score"] is not None and len(d["top"]) == 2


def test_api_key_not_in_db_and_env_takes_priority(core, monkeypatch):
    core.settings.set_api_key("AIzaSyFAKEKEYFAKEKEYFAKEKEYFAKEKEY12345")
    assert core.settings.api_key_source() == "settings"
    assert "FAKEKEY" not in open(core.db.path, "rb").read().decode("latin-1")
    monkeypatch.setenv("GEMINI_API_KEY", "from-env-key-1234567890")
    assert core.settings.get_api_key() == "from-env-key-1234567890"
    assert core.settings.api_key_source() == "environment"


# --------------------------------------------------------------------- reports
def test_reports_written(core, sample_files, tmp_path):
    (alice, bob), job_id = _setup(core, sample_files)
    rows, _ = core.rank(job_id)
    job = core.get_job(job_id)
    csv_path = tmp_path / "r.csv"
    reports.export_ranking_csv(csv_path, job, rows, blind=True)
    content = csv_path.read_text(encoding="utf-8-sig")
    assert "Alice" not in content and "Candidate #" in content
    reports.export_ranking_csv(csv_path, job, rows)
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        table = list(csv.reader(fh))
    assert table[3][1] == "Alice Example"

    cand = core.get_candidate(alice)
    m = core.get_match(alice, job_id)
    gap = core.skill_gap(alice, job_id)
    for name, fn in {
        "rank.pdf": lambda p: reports.export_ranking_pdf(p, job, rows),
        "match.pdf": lambda p: reports.export_match_pdf(p, cand, job, m),
        "gap.pdf": lambda p: reports.export_gap_pdf(p, cand, job, gap),
        "cand.pdf": lambda p: reports.export_candidate_pdf(p, cand, [(job, m)]),
    }.items():
        path = tmp_path / name
        fn(path)
        assert path.read_bytes().startswith(b"%PDF") and path.stat().st_size > 1500


def test_csv_formula_injection_is_neutralised():
    assert reports._csv_safe("=HYPERLINK(\"http://evil\")").startswith("'")
    assert reports._csv_safe("Normal") == "Normal"


def test_pdf_handles_markup_in_user_text(core, sample_files, tmp_path):
    (alice, _), job_id = _setup(core, sample_files)
    cand = core.get_candidate(alice)
    cand.professional_summary = "<b>unclosed <script>alert(1)</script> & stuff"
    job = core.get_job(job_id)
    m = core.get_match(alice, job_id) or core.match(alice, job_id)
    reports.export_candidate_pdf(tmp_path / "x.pdf", cand, [(job, m)])
    assert (tmp_path / "x.pdf").exists()
