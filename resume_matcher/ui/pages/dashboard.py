from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

from ..widgets import StatTile, button, chip, label, make_table, NumItem
from .base import Page
from PySide6.QtWidgets import QTableWidgetItem


class DashboardPage(Page):
    title = "Dashboard"
    subtitle = "An overview of your analyses. Results are decision support, not hiring decisions."

    def __init__(self, ctx, navigate):
        super().__init__(ctx)
        self.navigate = navigate
        tiles = QHBoxLayout()
        tiles.setSpacing(14)
        self.t_resumes = StatTile("Resumes analysed")
        self.t_jobs = StatTile("Jobs found")
        self.t_avg = StatTile("Average matching score")
        self.t_matches = StatTile("Match analyses")
        for t in (self.t_resumes, self.t_jobs, self.t_avg, self.t_matches):
            tiles.addWidget(t)
        self.root.addLayout(tiles)

        self.ai_note = chip("", "warn")
        self.root.addWidget(self.ai_note, 0, Qt.AlignLeft)

        actions = QHBoxLayout()
        actions.addWidget(label("QUICK ACTIONS", "section"))
        actions.addStretch(1)
        self.root.addLayout(actions)
        qa = QHBoxLayout()
        qa.setSpacing(8)
        qa.addWidget(button("Analyse resumes", primary=True, on_click=lambda: navigate("resume")))
        qa.addWidget(button("Find jobs", on_click=lambda: navigate("find")))
        qa.addWidget(button("Rank candidates", on_click=lambda: navigate("ranking")))
        qa.addWidget(button("Skill gap", on_click=lambda: navigate("gap")))
        qa.addStretch(1)
        self.root.addLayout(qa)

        cols = QHBoxLayout()
        cols.setSpacing(18)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(label("TOP MATCHING CANDIDATES", "section"))
        self.top = make_table(["Candidate", "Job", "Score"], stretch_col=1)
        left.addWidget(self.top, 1)
        right.addWidget(label("RECENT AI ANALYSES", "section"))
        self.recent = make_table(["Candidate", "Job", "Score", "When"], stretch_col=1)
        right.addWidget(self.recent, 1)
        cols.addLayout(left, 1)
        cols.addLayout(right, 1)
        self.root.addLayout(cols, 1)
        ctx.on_data_changed(self.refresh)

    def _fill(self, table, rows, with_when):
        table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(r["candidate"]))
            table.setItem(i, 1, QTableWidgetItem(r["job"]))
            table.setItem(i, 2, NumItem(r["score"]))
            if with_when:
                table.setItem(i, 3, QTableWidgetItem(r["when"].strftime("%d %b %H:%M")))

    def refresh(self) -> None:
        d = self.ctx.core.dashboard()
        self.t_resumes.set_value(str(d["resumes"]))
        self.t_jobs.set_value(str(d["jobs"]))
        self.t_avg.set_value("-" if d["avg_score"] is None else f"{d['avg_score']:.1f}")
        self.t_matches.set_value(str(d["matches"]))
        self._fill(self.top, d["top"], False)
        self._fill(self.recent, d["recent"], True)
        configured = self.ctx.core.ai.is_configured()
        self.ai_note.setVisible(not configured)
        self.ai_note.setText("Gemini API key not set - open Settings to enable AI analysis")
