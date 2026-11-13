"""Drives the real UI offscreen with the fake Gemini. Skipped when Qt cannot start."""

import os
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from conftest import JOB_TEXT
from fakes import FakeGemini
from resume_matcher.services import Core
from test_search import FakeProvider, P, DESC_GOOD, DESC_BAD
from resume_matcher.ui.main_window import MainWindow, NAV


@pytest.fixture()
def win(tmp_path, monkeypatch, sample_files):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real-1234567890")
    app = QApplication.instance() or QApplication([])
    core = Core(home=tmp_path / "home")
    core.ai = FakeGemini(core.settings, core.db)
    core.settings.update(disclosure_accepted=True)
    # never block on modal dialogs during tests
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Yes)
    w = MainWindow(core)
    w.show()
    yield w
    w.close()


def wait(cond, timeout=15):
    app = QCoreApplication.instance()
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_every_page_renders_in_both_themes(win):
    for theme in ("light", "dark", "light"):
        win.core.settings.update(theme=theme)
        win.apply_theme()
        for i in range(len(NAV)):
            win.nav.setCurrentRow(i)
            QCoreApplication.processEvents()
            assert win.stack.currentWidget() is win.pages[NAV[i][0]]


def test_full_workflow(win, sample_files, tmp_path):
    a, b = sample_files
    resume, find, ranking = win.pages["resume"], win.pages["find"], win.pages["ranking"]
    gap, reports = win.pages["gap"], win.pages["reports"]

    # 1. import resumes in the background
    resume.import_files([str(a), str(b)])
    assert wait(lambda: resume.list.count() == 2)
    assert "Imported 2" in resume.result_note.text()

    # 2. search for jobs (fake providers) and see ranked results
    win.core.providers = [
        FakeProvider("a", [P("a", "1", "Data Engineer", "Acme", DESC_GOOD, remote=True),
                           P("a", "2", "Data Engineer II", "Oldco", DESC_BAD)]),
        FakeProvider("down", error="Service down."),
    ]
    find.refresh()
    find.cand.setCurrentIndex(find.cand.findText("Alice", Qt.MatchStartsWith))
    find.roles.setText("data engineer")
    find.search()
    assert wait(lambda: len(find.results) == 2)
    assert len(find.rows) == 2 and find.selected is not None
    assert find.results[0].job.company_name == "Acme"
    assert "Why this score" in find.view.toPlainText()
    find.min_score.setValue(100)
    assert len(find.rows) == 0
    find.min_score.setValue(0)
    assert len(find.rows) == 2
    find.ov_score.setValue(55)
    find.apply_override()
    assert any(r.match.override_score == 55 for r in find.results)

    # 3. a manual job (internal API) so ranking / gap pages have something to use
    win.core.import_job_text(JOB_TEXT)
    win.ctx.data_changed()

    # 4. rank
    ranking.refresh()
    idx = ranking.job.findText("Senior Data Engineer", Qt.MatchStartsWith)
    assert idx > 0, [ranking.job.itemText(i) for i in range(ranking.job.count())]
    ranking.job.setCurrentIndex(idx)
    ranking.rank()
    assert wait(lambda: ranking.table.rowCount() == 2)
    assert ranking.table.item(0, 0).text() == "1"  # table starts in rank order
    assert "Alice" in ranking.table.item(0, 1).text()
    ranking.blind.setChecked(True)
    assert ranking.table.item(0, 1).text().startswith("Candidate #")
    ranking.blind.setChecked(False)
    ranking.search.setText("zzz-no-match")
    assert ranking.table.rowCount() == 0
    ranking.search.setText("")
    assert ranking.table.rowCount() == 2

    # 5. skill gap
    gap.refresh()
    gap.cand.setCurrentIndex(1)
    gap.job.setCurrentIndex(gap.job.findText("Senior Data Engineer", Qt.MatchStartsWith))
    gap.analyse()
    assert wait(lambda: gap.gap is not None)
    assert gap.table.rowCount() >= 4
    assert "Learn" in gap.view.toPlainText()

    # 6. dashboard + reports history
    win.pages["dashboard"].refresh()
    assert win.pages["dashboard"].t_resumes.value.text() == "2"
    reports.refresh()
    assert reports.table.rowCount() >= 1

    # 7. delete a candidate through the UI
    resume.list.setCurrentRow(0)
    resume.delete_selected()
    assert resume.list.count() == 1


def test_ai_failure_is_shown_not_raised(win, sample_files):
    from resume_matcher.errors import AIAuthError

    win.core.ai.responses = [AIAuthError("Gemini rejected the API key.")]
    shown = []
    win.ctx.show_error = lambda exc, title="": shown.append(exc)
    win.pages["resume"].import_files([str(sample_files[0])])
    assert wait(lambda: win.pages["resume"].result_note.text() != "" or shown)
    assert "rejected" in win.pages["resume"].result_note.text()
    assert win.pages["resume"].list.count() == 0


def test_missing_key_blocks_ai_actions(win, sample_files, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    win.core.ai.is_configured = lambda: False
    shown = []
    win.ctx.show_error = lambda exc, title="": shown.append(exc)
    win.pages["resume"].import_files([str(sample_files[0])])
    assert shown and "API key" in shown[0].user_message


def test_screenshots(win, sample_files):
    """Not an assertion: leaves PNGs in $RM_SHOTS for a visual check when that variable is set."""
    out = os.environ.get("RM_SHOTS")
    if not out:
        pytest.skip("RM_SHOTS not set")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    resume, find, ranking, gap = (win.pages[k] for k in ("resume", "find", "ranking", "gap"))
    resume.import_files([str(p) for p in sample_files])
    assert wait(lambda: resume.list.count() == 2)
    win.core.providers = [
        FakeProvider("remotive", [P("remotive", "1", "Senior Data Engineer", "Acme Corp", DESC_GOOD, remote=True, location="Worldwide", salary="$90k - $120k"),
                                  P("remotive", "2", "Data Platform Engineer", "Globex", DESC_GOOD + " Kubernetes.", location="Bengaluru"),
                                  P("remotive", "3", "Principal Data Architect", "Initech", DESC_BAD)]),
        FakeProvider("adzuna", key=True),
    ]
    find.refresh()
    find.cand.setCurrentIndex(find.cand.findText("Alice", Qt.MatchStartsWith))
    find.roles.setText("data engineer")
    find.search()
    assert wait(lambda: len(find.results) == 3)
    win.core.import_job_text(JOB_TEXT)
    win.ctx.data_changed()
    ranking.refresh()
    ranking.job.setCurrentIndex(ranking.job.findText("Senior Data Engineer", Qt.MatchStartsWith))
    ranking.rank()
    assert wait(lambda: ranking.table.rowCount() == 2)
    gap.refresh()
    gap.cand.setCurrentIndex(1)
    gap.job.setCurrentIndex(gap.job.findText("Senior Data Engineer", Qt.MatchStartsWith))
    gap.analyse()
    assert wait(lambda: gap.gap is not None)
    for theme in ("light", "dark"):
        win.core.settings.update(theme=theme)
        win.apply_theme()
        for i, (key, _t, _i) in enumerate(NAV):
            win.nav.setCurrentRow(i)
            for _ in range(5):
                QCoreApplication.processEvents()
            win.grab().save(str(out / f"{theme}_{key}.png"))
