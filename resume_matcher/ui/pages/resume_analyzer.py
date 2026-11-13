from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QSplitter, QTextBrowser, QVBoxLayout, QWidget

from ...scoring import level_rank
from ..widgets import BusyBar, DropZone, banner, button, chips_html, esc, label
from .base import Page


class ResumeAnalyzerPage(Page):
    title = "Resume Analyzer"
    subtitle = "Upload resumes to extract a structured candidate profile with Gemini."

    def __init__(self, ctx):
        super().__init__(ctx)
        self.drop = DropZone(
            "Drop resumes here",
            "Supported formats: PDF and DOCX. You can select several files at once.",
            "Resumes (*.pdf *.docx);;PDF (*.pdf);;Word (*.docx)",
            extensions=(".pdf", ".docx"),
        )
        self.drop.files_selected.connect(self.import_files)
        self.root.addWidget(self.drop)
        self.root.addWidget(banner(
            "Privacy: resume text is sent to Google's Gemini API for parsing. Results are stored only on this computer.",
            "info"))
        self.busy = BusyBar()
        self.root.addWidget(self.busy)
        self.result_note = label("", "small", wrap=True)
        self.root.addWidget(self.result_note)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(label("CANDIDATES", "section"))
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._show)
        ll.addWidget(self.list, 1)
        self.delete_btn = button("Delete candidate and data", danger=True, on_click=self.delete_selected)
        ll.addWidget(self.delete_btn)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        split.addWidget(left)
        split.addWidget(self.view)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        self.root.addWidget(split, 1)
        ctx.on_data_changed(self.refresh)

    # ------------------------------------------------------------------
    def apply_theme(self) -> None:
        self.drop.set_icon_color(self.ctx.colors["accent"])
        self._show(self.list.currentItem(), None)

    def refresh(self) -> None:
        cur = self._current_id()
        self.list.blockSignals(True)
        self.list.clear()
        for c in self.ctx.core.list_candidates():
            it = QListWidgetItem(f"{c.candidate_name}\n{c.total_experience:g} yrs  -  {len(c.skills)} skills")
            it.setData(Qt.UserRole, c.candidate_id)
            self.list.addItem(it)
            if c.candidate_id == cur:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._show(self.list.currentItem(), None)
        self.delete_btn.setEnabled(self.list.count() > 0)

    def _current_id(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    # ------------------------------------------------------------------
    def import_files(self, paths: list[str]) -> None:
        if not self.ctx.ensure_ai_ready():
            return
        self.result_note.setText("")

        def work(progress):
            return self.ctx.core.import_resumes([Path(p) for p in paths], progress)

        def done(outcomes):
            ok = [o for o in outcomes if o.candidate_id and not o.duplicate]
            dup = [o for o in outcomes if o.duplicate]
            bad = [o for o in outcomes if o.error]
            lines = []
            if ok:
                lines.append(f"Imported {len(ok)} resume(s).")
            if dup:
                lines.append(f"{len(dup)} already imported (skipped).")
            for o in bad:
                lines.append(f"{o.file_name}: {o.error}")
            self.result_note.setText("\n".join(lines))
            self.ctx.status(f"Imported {len(ok)} of {len(outcomes)} file(s)")
            self.ctx.data_changed()
            if ok:
                self._select(ok[-1].candidate_id)

        self.busy.start("Reading resumes...", len(paths))
        self.ctx.run(work, done, on_progress=self.busy.update_progress,
                     busy=lambda b: (self.drop.set_busy(b), None if b else self.busy.stop()))

    def _select(self, cid: int) -> None:
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == cid:
                self.list.setCurrentRow(i)
                return

    def delete_selected(self) -> None:
        cid = self._current_id()
        if cid is None:
            return
        if self.ctx.confirm("Delete candidate",
                            "Delete this candidate, their resume file and all related analyses? This cannot be undone.",
                            danger=True):
            self.ctx.core.delete_candidate(cid)
            self.ctx.data_changed()

    # ------------------------------------------------------------------
    def _show(self, item, _prev) -> None:
        if item is None:
            self.view.setHtml(f"<p style='color:{self.ctx.colors['muted']}'>No candidate selected. Import a resume to begin.</p>")
            return
        c = self.ctx.core.get_candidate(item.data(Qt.UserRole))
        p = c.profile_json or {}
        col = self.ctx.colors
        h = [f"<h2 style='margin:0'>{esc(c.candidate_name)}</h2>"]
        contact = " &middot; ".join(esc(x) for x in (c.email, c.phone, p.get("location")) if x)
        if contact:
            h.append(f"<p style='color:{col['muted']}'>{contact}</p>")
        h.append(f"<p>{esc(c.professional_summary or '')}</p>")
        h.append(f"<p><b>Total experience:</b> {c.total_experience:g} years</p>")
        by_cat: dict[str, list[str]] = {}
        for s in c.skills:
            by_cat.setdefault((s.skill_category or "technical").title(), []).append(s.skill_name)
        h.append("<h3>Skills</h3>")
        for cat, names in by_cat.items():
            h.append(f"<p><b>{esc(cat)}</b><br>{chips_html(names, col['accent'], col['sel'])}</p>")
        h.append("<h3>Experience</h3>")
        for e in p.get("experience", []):
            span = " - ".join(x for x in (e.get("start"), e.get("end")) if x)
            h.append(f"<p><b>{esc(e.get('title',''))}</b> &middot; {esc(e.get('company',''))} "
                     f"<span style='color:{col['muted']}'>{esc(span)}</span><br>{esc(e.get('description',''))}</p>")
        if not p.get("experience"):
            h.append(f"<p style='color:{col['muted']}'>No work experience found.</p>")
        h.append("<h3>Education</h3>")
        for e in p.get("education", []):
            line = " ".join(x for x in (e.get("degree"), e.get("field")) if x)
            inst = f", {e['institution']}" if e.get("institution") else ""
            yr = f" ({e['year']})" if e.get("year") else ""
            h.append(f"<p>{esc(line + inst + yr)}</p>")
        if p.get("projects"):
            h.append("<h3>Projects</h3>")
            for pr in p["projects"]:
                h.append(f"<p><b>{esc(pr.get('name',''))}</b> - {esc(pr.get('description',''))}</p>")
        if p.get("certifications"):
            h.append("<h3>Certifications</h3><ul>" + "".join(f"<li>{esc(x)}</li>" for x in p["certifications"]) + "</ul>")
        if p.get("languages"):
            h.append(f"<h3>Languages</h3><p>{esc(', '.join(p['languages']))}</p>")
        res = c.resumes[0].file_name if c.resumes else ""
        h.append(f"<p style='color:{col['muted']}'>Source: {esc(res)}</p>")
        self.view.setHtml("".join(h))
