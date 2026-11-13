from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QTableWidgetItem

from ... import reports
from ..widgets import NumItem, banner, button, label, make_table, tile
from .base import Page, fill_combo


class ReportsPage(Page):
    title = "Reports"
    subtitle = "Export candidate, job-matching and skill-gap reports as PDF, and ranking reports as CSV or PDF."

    def __init__(self, ctx):
        super().__init__(ctx)
        box = tile()
        grid = QGridLayout(box)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.cand = QComboBox()
        self.job = QComboBox()
        self.blind = QCheckBox("Blind reports (replace names with candidate numbers)")
        grid.addWidget(label("Candidate", "muted"), 0, 0)
        grid.addWidget(self.cand, 0, 1)
        grid.addWidget(label("Job", "muted"), 0, 2)
        grid.addWidget(self.job, 0, 3)
        grid.addWidget(self.blind, 1, 0, 1, 4)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addWidget(button("Candidate analysis (PDF)", on_click=self.candidate_pdf))
        btns.addWidget(button("Job compatibility (PDF)", on_click=self.match_pdf))
        btns.addWidget(button("Skill gap (PDF)", on_click=self.gap_pdf))
        btns.addWidget(button("Ranking (PDF)", on_click=lambda: self.ranking("pdf")))
        btns.addWidget(button("Ranking (CSV)", primary=True, on_click=lambda: self.ranking("csv")))
        btns.addStretch(1)
        grid.addLayout(btns, 2, 0, 1, 4)
        self.root.addWidget(box)
        self.root.addWidget(label("ANALYSIS HISTORY", "section"))
        self.table = make_table(["Candidate", "Job", "Score", "Date"], stretch_col=1)
        self.root.addWidget(self.table, 1)
        self.root.addWidget(banner("Reports include a notice that AI results are decision support and not hiring decisions.", "info"))
        ctx.on_data_changed(self.refresh)

    def refresh(self) -> None:
        fill_combo(self.cand, [(f"{c.candidate_name}  (#{c.candidate_id})", c.candidate_id) for c in self.ctx.core.list_candidates()], "Select a candidate...")
        fill_combo(self.job, [(f"{j.job_title} · {j.company_name}" if j.company_name else j.job_title, j.job_id) for j in self.ctx.core.list_jobs(limit=300)], "Select a job...")
        hist = self.ctx.core.history()
        self.table.setRowCount(len(hist))
        for i, h in enumerate(hist):
            self.table.setItem(i, 0, QTableWidgetItem(h["candidate"]))
            self.table.setItem(i, 1, QTableWidgetItem(h["job"]))
            self.table.setItem(i, 2, NumItem(h["score"], f"{h['score']:.0f}"))
            self.table.setItem(i, 3, QTableWidgetItem(h["when"].strftime("%d %b %Y %H:%M")))

    # ------------------------------------------------------------------
    def _ids(self, need_cand=True, need_job=True):
        cid, jid = self.cand.currentData(), self.job.currentData()
        if (need_cand and cid is None) or (need_job and jid is None):
            what = " and ".join(x for x, n in (("a candidate", need_cand), ("a job", need_job)) if n)
            self.ctx.info("Selection needed", f"Please select {what}.")
            return None
        return cid, jid

    def _save(self, default: str, flt: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, "Save report", default, flt)
        return path

    def _guard(self, fn) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            self.ctx.show_error(exc)

    def candidate_pdf(self) -> None:
        ids = self._ids(need_job=False)
        if not ids:
            return
        path = self._save("candidate_report.pdf", "PDF (*.pdf)")
        if path:
            def go():
                core = self.ctx.core
                cand = core.get_candidate(ids[0])
                pairs = []
                for j in core.list_jobs():
                    m = core.get_match(cand.candidate_id, j.job_id)
                    if m:
                        pairs.append((j, m))
                reports.export_candidate_pdf(path, cand, pairs, self.blind.isChecked())
                self.ctx.status(f"Saved {path}")
            self._guard(go)

    def match_pdf(self) -> None:
        ids = self._ids()
        if not ids:
            return
        m = self.ctx.core.get_match(*ids)
        if m is None:
            self.ctx.info("No analysis yet", "Run the analysis in the Job Matcher for this candidate and job first.")
            return
        path = self._save("job_compatibility_report.pdf", "PDF (*.pdf)")
        if path:
            self._guard(lambda: (reports.export_match_pdf(path, self.ctx.core.get_candidate(ids[0]),
                                                          self.ctx.core.get_job(ids[1]), m, self.blind.isChecked()),
                                 self.ctx.status(f"Saved {path}")))

    def gap_pdf(self) -> None:
        ids = self._ids()
        if not ids:
            return
        if not self.ctx.ensure_ai_ready():
            return
        path = self._save("skill_gap_report.pdf", "PDF (*.pdf)")
        if not path:
            return

        def work():
            gap = self.ctx.core.skill_gap(*ids)
            reports.export_gap_pdf(path, self.ctx.core.get_candidate(ids[0]), self.ctx.core.get_job(ids[1]), gap,
                                   self.blind.isChecked())

        self.ctx.run(work, lambda _r: self.ctx.status(f"Saved {path}"))

    def ranking(self, kind: str) -> None:
        ids = self._ids(need_cand=False)
        if not ids:
            return
        rows = self.ctx.core.ranking_from_history(ids[1])
        if not rows:
            self.ctx.info("No ranking yet", "Rank candidates for this job on the Candidate Ranking screen first.")
            return
        path = self._save(f"candidate_ranking.{kind}", "CSV (*.csv)" if kind == "csv" else "PDF (*.pdf)")
        if path:
            job = self.ctx.core.get_job(ids[1])
            fn = reports.export_ranking_csv if kind == "csv" else reports.export_ranking_pdf
            self._guard(lambda: (fn(path, job, rows, self.blind.isChecked()), self.ctx.status(f"Saved {path}")))
