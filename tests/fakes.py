"""A deterministic stand-in for the Gemini network call, used by tests and the UI smoke test."""

from __future__ import annotations

import json
import re

from resume_matcher.ai.gemini import GeminiService

KNOWN = [
    "Python", "SQL", "Machine Learning", "Docker", "AWS", "Kubernetes", "React", "TypeScript",
    "PostgreSQL", "Java", "Communication", "Leadership", "TensorFlow", "Git", "Linux", "Excel",
]


def _between(prompt: str, start="<<<DOCUMENT\n", end="\nDOCUMENT>>>") -> str:
    i = prompt.find(start)
    j = prompt.rfind(end)
    return prompt[i + len(start) : j] if i != -1 and j != -1 else ""


class FakeGemini(GeminiService):
    """Overrides only the raw network call; caching, validation and retries are the real code."""

    def __init__(self, settings, db, responses=None):
        super().__init__(settings, db, sleep=lambda _s: None)
        self.calls: list[str] = []
        self.responses = list(responses or [])  # scripted raw outputs / exceptions (consumed first)

    def is_configured(self) -> bool:
        return True

    def _raw_generate(self, prompt: str) -> str:
        task = prompt.splitlines()[0].replace("TASK:", "").strip()
        self.calls.append(task)
        if self.responses:
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return json.dumps(getattr(self, f"_{task}")(prompt))

    # -- canned behaviours ---------------------------------------------------
    def _ping(self, prompt):
        return {"ok": True}

    def _parse_resume(self, prompt):
        text = _between(prompt)
        first = text.strip().splitlines()[0].strip()
        skills = [{"name": k, "category": "technical"} for k in KNOWN if re.search(rf"\b{re.escape(k)}\b", text, re.I)]
        years = 0.0
        m = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*years", text, re.I)
        if m:
            years = float(m.group(1))
        level = "master" if re.search(r"master|m\.sc", text, re.I) else "bachelor" if re.search(r"bachelor|b\.sc|b\.tech", text, re.I) else "other"
        email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
        return {
            "name": first,
            "email": email.group(0) if email else None,
            "summary": f"Professional with {years:g} years of experience.",
            "skills": skills,
            "education": [{"degree": "Bachelor of Science" if level == "bachelor" else "Master of Science" if level == "master" else "", "field": "Computer Science", "institution": "Test University", "level": level}],
            "experience": [{"title": "Engineer", "company": "Acme", "duration_months": int(years * 12), "description": "Built data pipelines and services."}],
            "projects": [],
            "certifications": ["AWS Certified Cloud Practitioner"] if "AWS Certified" in text else [],
            "languages": ["English"],
            "total_experience_years": years,
        }

    def _analyze_job(self, prompt):
        text = _between(prompt)
        skills = []
        for k in KNOWN:
            if re.search(rf"\b{re.escape(k)}\b", text, re.I):
                nice = re.search(rf"(preferred|nice to have|bonus)[^.\n]*\b{re.escape(k)}\b", text, re.I)
                skills.append({"name": k, "importance": "nice_to_have" if nice else "must_have"})
        m = re.search(r"(\d+)\+?\s*years", text, re.I)
        return {
            "title": text.strip().splitlines()[0].strip()[:80] or "Role",
            "company": "Acme Corp",
            "location": "Remote" if "remote" in text.lower() else "Bengaluru",
            "work_mode": "remote" if "remote" in text.lower() else "on-site",
            "required_experience_years": float(m.group(1)) if m else None,
            "required_education": "bachelor" if "bachelor" in text.lower() else None,
            "skills": skills,
            "certifications": [],
            "responsibilities": ["Build and operate services"],
            "summary": "Test role.",
        }

    def _assess_match(self, prompt):
        m = re.search(r'"skills": \[(.*?)\]\n', prompt, re.S)
        return {
            "semantic_score": 70,
            "strengths": ["Relevant hands-on experience"],
            "concerns": [],
            "uncertainties": [],
            "explanation": "The candidate's experience is relevant to the role's responsibilities.",
            "skill_equivalences": [{"job_skill": "SQL", "candidate_skill": "PostgreSQL"}],
        }

    def _skill_gap_advice(self, prompt):
        names = re.findall(r'"name": "([^"]+)"', prompt.split("CANDIDATE BACKGROUND")[0])
        return {"items": [{"skill": n, "difficulty": "moderate", "estimated_weeks": 4,
                           "learning_path": [f"Learn {n} basics", f"Build a small {n} project"],
                           "certifications": [], "projects": [f"Deploy a demo using {n}"]} for n in names]}

    def _suggest_roles(self, prompt):
        return {"roles": [{"title": "Data Engineer", "rationale": "Strong Python and SQL.", "fit": "strong", "key_skills": ["Python", "SQL"]}]}
