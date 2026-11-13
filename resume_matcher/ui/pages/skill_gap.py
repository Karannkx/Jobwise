from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QSplitter, QTableWidgetItem, QTextBrowser

from ... import reports
from ..widgets import BusyBar, banner, button, esc, label, make_table
from .base import Page, fill_combo

STATUS_TEXT = {"listed": "Has skill", "mentioned": "Mentioned in experience", "equivalent": "Equivalent skill", "missing": "Missing"}
IMPORTANCE_TEXT = {"must_have": "Must have", "important": "Important", "nice_to_have": "Nice to have"}


class SkillGapPage(Page):
    title = "Skill Gap Analyzer"
    subtitle = "Compare required and available skills and get suggested ways to close the gaps."

    def __init__(self, ctx):
        super().__init__(ctx)
        self.gap = None
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.cand = QComboBox()
        self.cand.setMinimumWidth(220)
        self.job = QComboBox()
        self.job.setMinimumWidth(220)
        self.run_btn = button("Analyse gaps", primary=True, on_click=self.analyse)
        self.pdf_btn = button("Export PDF", on_click=self.export_pdf)
        for w in (label("Candidate:", "muted"), self.cand, label("Job:", "muted"), self.job, self.run_btn):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.pdf_btn)
        self.root.addLayout(bar)
        self.busy = BusyBar()
        self.root.addWidget(self.busy)

        split = QSplitter(Qt.Horizontal)
        self.table = make_table(["Required skill", "Importance", "Status"], stretch_col=0)
        split.addWidget(self.table)
        self.view = QTextBrowser()
        split.addWidget(self.view)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        self.root.addWidget(split, 1)
        self.root.addWidget(banner("Learning recommendations are suggestions only. Completing them does not guarantee a qualification or a job.", "info"))
        self._render()
        ctx.on_data_changed(self.refresh)

    def refresh(self) -> None:
        fill_combo(self.cand, [(f"{c.candidate_name}  (#{c.candidate_id})", c.candidate_id) for c in self.ctx.core.list_candidates()], "Select a candidate...")
        fill_combo(self.job, [(f"{j.job_title} · {j.company_name}" if j.company_name else j.job_title, j.job_id) for j in self.ctx.core.list_jobs(limit=300)], "Select a job...")

    def apply_theme(self) -> None:
        self._render()

    def analyse(self) -> None:
        cid, jid = self.cand.currentData(), self.job.currentData()
        if cid is None or jid is None:
            self.ctx.info("Select both", "Please select a candidate and a job.")
            return
        if not self.ctx.ensure_ai_ready():
            return

        def done(g):
            self.gap = g
            self._render()
            self.ctx.status("Skill gap analysis complete")
            self.ctx.data_changed()

        self.busy.start("Analysing skill gaps...")
        self.ctx.run(lambda: self.ctx.core.skill_gap(cid, jid), done,
                     busy=lambda b: (self.run_btn.setEnabled(not b), None if b else self.busy.stop()))

    def _render(self) -> None:
        col = self.ctx.colors
        g = self.gap
        self.pdf_btn.setEnabled(g is not None)
        if g is None:
            self.table.setRowCount(0)
            self.view.setHtml(f"<p style='color:{col['muted']}'>Select a candidate and a job, then press <b>Analyse gaps</b>.</p>")
            return
        status = g.skill_status or []
        self.table.setRowCount(len(status))
        for i, s in enumerate(status):
            self.table.setItem(i, 0, QTableWidgetItem(s["name"]))
            self.table.setItem(i, 1, QTableWidgetItem(IMPORTANCE_TEXT.get(s["importance"], s["importance"])))
            st = QTableWidgetItem(("✓ " if s["status"] != "missing" else "✗ ") + STATUS_TEXT.get(s["status"], s["status"]))
            st.setForeground(QBrush(QColor(col["good"] if s["status"] != "missing" else col["bad"])))
            self.table.setItem(i, 2, st)
        recs = g.recommendations or []
        if not recs:
            self.view.setHtml("<h3>No skill gaps</h3><p>The candidate covers every skill listed for this job.</p>")
            return
        h = ["<h3 style='margin:0'>Suggested ways to close the gaps</h3>"]
        for r in recs:
            meta = []
            if r.get("difficulty"):
                meta.append(f"difficulty: {r['difficulty']}")
            if r.get("estimated_weeks"):
                meta.append(f"about {r['estimated_weeks']} weeks")
            h.append(f"<h4>{esc(r['skill'])} <span style='color:{col['muted']};font-weight:normal'>"
                     f"({esc(IMPORTANCE_TEXT.get(r['importance'], r['importance']))}{'; ' + esc(', '.join(meta)) if meta else ''})</span></h4>")
            if r.get("note"):
                h.append(f"<p style='color:{col['muted']}'>{esc(r['note'])}</p>")
            for lab, key in (("Learning path", "learning_path"), ("Certifications", "certifications"), ("Practice projects", "projects")):
                if r.get(key):
                    h.append(f"<p><b>{lab}</b></p><ul>" + "".join(f"<li>{esc(x)}</li>" for x in r[key]) + "</ul>")
        self.view.setHtml("".join(h))

    def export_pdf(self) -> None:
        if self.gap is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export skill gap report", "skill_gap_report.pdf", "PDF (*.pdf)")
        if path:
            try:
                reports.export_gap_pdf(path, self.ctx.core.get_candidate(self.gap.candidate_id),
                                       self.ctx.core.get_job(self.gap.job_id), self.gap)
                self.ctx.status(f"Saved {path}")
            except Exception as exc:  # noqa: BLE001
                self.ctx.show_error(exc)
