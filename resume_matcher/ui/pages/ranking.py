from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLineEdit, QSplitter,
    QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from ... import reports
from ..theme import score_color
from ..widgets import BusyBar, NumItem, button, chips_html, esc, label, make_table
from .base import Page, fill_combo


class RankingPage(Page):
    title = "Candidate Ranking"
    subtitle = "Rank every imported candidate against a job. Scores are explainable and can be overridden by a reviewer."

    HEADERS = ["Rank", "Candidate", "Score", "Skills", "Experience", "Qualif.", "Years", "Missing skills"]

    def __init__(self, ctx):
        super().__init__(ctx)
        self.rows = []
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.job = QComboBox()
        self.job.setMinimumWidth(260)
        self.job.currentIndexChanged.connect(self._job_changed)
        bar.addWidget(label("Job:", "muted"))
        bar.addWidget(self.job)
        self.run_btn = button("Rank candidates", primary=True, on_click=self.rank)
        bar.addWidget(self.run_btn)
        bar.addStretch(1)
        self.blind = QCheckBox("Blind review (hide names)")
        self.blind.toggled.connect(lambda _=False: self._fill())
        bar.addWidget(self.blind)
        self.root.addLayout(bar)

        flt = QHBoxLayout()
        flt.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name or skill...")
        self.search.textChanged.connect(lambda _=None: self._fill())
        self.min_score = QDoubleSpinBox()
        self.min_score.setRange(0, 100)
        self.min_score.setDecimals(0)
        self.min_score.valueChanged.connect(lambda _=None: self._fill())
        self.min_exp = QDoubleSpinBox()
        self.min_exp.setRange(0, 60)
        self.min_exp.setDecimals(1)
        self.min_exp.valueChanged.connect(lambda _=None: self._fill())
        flt.addWidget(self.search, 1)
        flt.addWidget(label("Min score", "muted"))
        flt.addWidget(self.min_score)
        flt.addWidget(label("Min years", "muted"))
        flt.addWidget(self.min_exp)
        flt.addWidget(button("Export CSV", on_click=self.export_csv))
        flt.addWidget(button("Export PDF", on_click=self.export_pdf))
        self.root.addLayout(flt)
        self.busy = BusyBar()
        self.root.addWidget(self.busy)
        self.note = label("", "small", wrap=True)
        self.root.addWidget(self.note)

        split = QSplitter(Qt.Vertical)
        self.table = make_table(self.HEADERS, stretch_col=7)
        self.table.setSortingEnabled(True)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 200)
        for c in range(2, 7):
            self.table.setColumnWidth(c, 90)
        self.table.itemSelectionChanged.connect(self._show_detail)
        split.addWidget(self.table)
        self.detail = QTextBrowser()
        split.addWidget(self.detail)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self.root.addWidget(split, 1)
        ctx.on_data_changed(self.refresh)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        fill_combo(self.job, [(f"{j.job_title} · {j.company_name}" if j.company_name else j.job_title, j.job_id) for j in self.ctx.core.list_jobs(limit=300)], "Select a job...")
        self._job_changed()

    def _job_changed(self) -> None:
        jid = self.job.currentData()
        self.rows = self.ctx.core.ranking_from_history(jid) if jid is not None else []
        self._fill()

    def rank(self) -> None:
        jid = self.job.currentData()
        if jid is None:
            self.ctx.info("Select a job", "Please select a job to rank candidates against.")
            return
        if not self.ctx.core.list_candidates():
            self.ctx.info("No candidates", "Import resumes in the Resume Analyzer first.")
            return
        if not self.ctx.ensure_ai_ready():
            return

        def done(result):
            rows, failures = result
            self.rows = rows
            self._fill()
            self.note.setText("\n".join(f"{n}: {r}" for n, r in failures[:6]))
            self.ctx.status(f"Ranked {len(rows)} candidate(s)")
            self.ctx.data_changed()

        self.busy.start("Ranking candidates...", 1)
        self.ctx.run(lambda p: self.ctx.core.rank(jid, progress=p), done,
                     on_progress=self.busy.update_progress,
                     busy=lambda b: (self.run_btn.setEnabled(not b), None if b else self.busy.stop()))

    # ------------------------------------------------------------------
    def _name(self, r) -> str:
        return reports.display_name(r.candidate, self.blind.isChecked())

    def _visible(self):
        q = self.search.text().strip().lower()
        out = []
        for r in self.rows:
            if r.final_score < self.min_score.value() or (r.candidate.total_experience or 0) < self.min_exp.value():
                continue
            if q:
                hay = (self._name(r) + " " + " ".join(s.skill_name for s in r.candidate.skills)).lower()
                if q not in hay:
                    continue
            out.append(r)
        return out

    def _fill(self) -> None:
        col = self.ctx.colors
        rows = self._visible()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            m = r.match
            missing = ", ".join((m.details or {}).get("missing_skills", [])) or "-"
            rank_item = NumItem(i + 1, str(i + 1))
            rank_item.setData(Qt.UserRole, r.candidate.candidate_id)
            self.table.setItem(i, 0, rank_item)
            self.table.setItem(i, 1, QTableWidgetItem(self._name(r) + ("  (reviewed)" if m.override_score is not None else "")))
            sc = NumItem(r.final_score, f"{r.final_score:.0f}")
            sc.setForeground(QBrush(QColor(score_color(r.final_score, col))))
            f = sc.font()
            f.setBold(True)
            sc.setFont(f)
            self.table.setItem(i, 2, sc)
            self.table.setItem(i, 3, NumItem(m.skill_score, "n/a" if m.skill_score is None else f"{m.skill_score:.0f}"))
            self.table.setItem(i, 4, NumItem(m.experience_score, "n/a" if m.experience_score is None else f"{m.experience_score:.0f}"))
            self.table.setItem(i, 5, NumItem(m.qualification_score, "n/a" if m.qualification_score is None else f"{m.qualification_score:.0f}"))
            self.table.setItem(i, 6, NumItem(r.candidate.total_experience, f"{r.candidate.total_experience:g}"))
            self.table.setItem(i, 7, QTableWidgetItem(missing))
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.AscendingOrder)  # always start from rank order
        if rows:
            self.table.selectRow(0)
        else:
            self.detail.setHtml(f"<p style='color:{col['muted']}'>"
                                + ("No ranking yet. Select a job and press <b>Rank candidates</b>." if not self.rows else "No candidates match the current filters.")
                                + "</p>")

    def _selected(self):
        items = self.table.selectedItems()
        if not items:
            return None
        cid = self.table.item(items[0].row(), 0).data(Qt.UserRole)
        return next((r for r in self.rows if r.candidate.candidate_id == cid), None)

    def _show_detail(self) -> None:
        r = self._selected()
        if r is None:
            return
        col = self.ctx.colors
        m, d = r.match, r.match.details or {}
        h = [f"<h3 style='margin:0'>{esc(self._name(r))} - {m.final_score:.0f}/100</h3>",
             f"<p>{esc(m.analysis_explanation or '')}</p>",
             "<p><b>Matched:</b> " + chips_html(d.get("matched_skills", []), col["good"], col["good_bg"]) + "</p>",
             "<p><b>Missing:</b> " + chips_html(d.get("missing_skills", []), col["bad"], col["bad_bg"]) + "</p>"]
        if d.get("concerns"):
            h.append("<p><b>Concerns:</b> " + esc("; ".join(d["concerns"])) + "</p>")
        if d.get("uncertainties"):
            h.append(f"<p style='color:{col['muted']}'><b>Uncertain:</b> " + esc("; ".join(d["uncertainties"])) + "</p>")
        if m.override_score is not None:
            h.append(f"<p><b>Reviewer override:</b> {m.override_score:.0f}" + (f" - {esc(m.override_note)}" if m.override_note else "") + "</p>")
        h.append(f"<p style='color:{col['muted']}'>Open the Job Matcher to override this score.</p>")
        self.detail.setHtml("".join(h))

    # ------------------------------------------------------------------ export
    def _need_rows(self):
        rows = self._visible()
        jid = self.job.currentData()
        if jid is None or not rows:
            self.ctx.info("Nothing to export", "Rank candidates for a job first.")
            return None
        return self.ctx.core.get_job(jid), rows

    def export_csv(self) -> None:
        got = self._need_rows()
        if not got:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export ranking", "candidate_ranking.csv", "CSV (*.csv)")
        if path:
            try:
                reports.export_ranking_csv(path, got[0], got[1], self.blind.isChecked())
                self.ctx.status(f"Saved {path}")
            except Exception as exc:  # noqa: BLE001
                self.ctx.show_error(exc)

    def export_pdf(self) -> None:
        got = self._need_rows()
        if not got:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export ranking", "candidate_ranking.pdf", "PDF (*.pdf)")
        if path:
            try:
                reports.export_ranking_pdf(path, got[0], got[1], self.blind.isChecked())
                self.ctx.status(f"Saved {path}")
            except Exception as exc:  # noqa: BLE001
                self.ctx.show_error(exc)
