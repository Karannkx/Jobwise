from resume_matcher import scoring
from resume_matcher.config import ScoringWeights


def prof(skills, text="", years=3, certs=None):
    return {
        "skills": [{"name": s} for s in skills],
        "summary": text,
        "experience": [],
        "projects": [],
        "certifications": certs or [],
        "total_experience_years": years,
    }


def test_alias_normalisation():
    assert scoring.norm_skill("JS") == "javascript"
    assert scoring.norm_skill(" Amazon Web Services ") == "aws"
    assert scoring.norm_skill("Scikit Learn") == "scikit-learn"


def test_prd_example_skill_gap():
    job = [{"name": n, "importance": "must_have"} for n in ["Python", "SQL", "Machine Learning", "Docker", "AWS"]]
    matches = scoring.match_skills(job, prof(["Python", "SQL", "Machine Learning"]))
    missing = [m.skill for m in matches if m.status == "missing"]
    assert missing == ["Docker", "AWS"]
    assert scoring.skill_score(matches) == 60.0


def test_directional_containment():
    job = [{"name": "SQL", "importance": "important"}]
    assert scoring.match_skills(job, prof(["SQL Server"]))[0].status == "listed"
    job = [{"name": "React Native", "importance": "important"}]
    assert scoring.match_skills(job, prof(["React"]))[0].status == "missing"
    job = [{"name": "Java", "importance": "important"}]
    assert scoring.match_skills(job, prof(["JavaScript"]))[0].status == "missing"


def test_mentioned_in_text_gets_partial_credit():
    job = [{"name": "Docker", "importance": "must_have"}]
    m = scoring.match_skills(job, prof([], text="Deployed services with Docker and Compose"))
    assert m[0].status == "mentioned"
    assert scoring.skill_score(m) == 80.0


def test_equivalence_partial_credit():
    job = [{"name": "SQL", "importance": "must_have"}]
    m = scoring.match_skills(job, prof(["PostgreSQL"]), {"SQL": "PostgreSQL"})
    assert m[0].status == "equivalent"
    assert scoring.skill_score(m) == 70.0


def test_importance_weighting():
    job = [{"name": "A1", "importance": "must_have"}, {"name": "B1", "importance": "nice_to_have"}]
    m = scoring.match_skills(job, prof(["A1"]))
    assert scoring.skill_score(m) == 75.0  # 3 of 4 weight


def test_experience_score():
    assert scoring.experience_score(2, 4) == 50.0
    assert scoring.experience_score(10, 4) == 100.0
    assert scoring.experience_score(1, None) is None
    assert scoring.experience_score(0, 0) == 100.0


def test_education_levels():
    assert scoring.level_rank("bachelor") == 3
    assert scoring.level_rank("M.Sc. in Physics") == 4
    assert scoring.level_rank("PhD") == 5
    assert scoring.qualification_score(3, "master", [], []) == 65.0
    assert scoring.qualification_score(4, "bachelor", [], []) == 100.0
    assert scoring.qualification_score(0, None, [], []) is None


def test_combine_renormalises_missing_components():
    w = ScoringWeights()
    overall, used, notes = scoring.combine(w, 80.0, None, None, None)
    assert overall == 80.0
    assert used == {"skills": 1.0}
    assert len(notes) == 3


def test_combine_is_configurable_and_not_llm_only():
    llm_heavy = ScoringWeights(skills=0.1, experience=0.1, qualification=0.1, semantic=0.7)
    o1, _, _ = scoring.combine(llm_heavy, 0, 0, 0, 100)
    o2, _, _ = scoring.combine(ScoringWeights(), 0, 0, 0, 100)
    assert o1 > o2
    # With default weights an LLM score of 100 cannot dominate poor structured scores.
    assert o2 < 20
