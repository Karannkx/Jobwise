import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from fakes import FakeGemini
from resume_matcher.services import Core


@pytest.fixture()
def core(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    c = Core(home=tmp_path / "home")
    c.ai = FakeGemini(c.settings, c.db)
    yield c
    c.close()


RESUME_ALICE = """Alice Example
alice@example.com | +1 555 010 7788
Summary: Data engineer with 5 years of experience.
Skills: Python, PostgreSQL, Docker, Machine Learning, Git
Bachelor of Science in Computer Science, Test University
AWS Certified Cloud Practitioner
Engineer at Acme (2019-2024): built data pipelines using Python and Docker.
"""

RESUME_BOB = """Bob Sample
bob@example.com
Summary: Junior developer with 1 years of experience.
Skills: Java, Excel, Communication
Experience: Intern building small tools in Java.
"""

JOB_TEXT = """Senior Data Engineer
We are hiring remotely. Bachelor degree required, 4+ years experience.
Required: Python, SQL, Docker, AWS, Kubernetes.
Preferred: Machine Learning.
"""


@pytest.fixture()
def sample_files(tmp_path):
    a = tmp_path / "alice.txt"
    a.write_text(RESUME_ALICE, encoding="utf-8")
    b = tmp_path / "bob.txt"
    b.write_text(RESUME_BOB, encoding="utf-8")
    return a, b
