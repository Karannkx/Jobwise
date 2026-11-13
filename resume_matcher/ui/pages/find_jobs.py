"""Find Jobs: search many job boards, score every result against a candidate, show the best fits first."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
    QScrollArea, QSplitter, QTextBrowser, QVBoxLayout, QWidget,
)

from ...search_mixin import JobResult, SearchOutcome
from .. import icons
from ..theme import score_color
from ..widgets import BusyBar, MiniBar, ScoreRing, button, chip, chips_html, esc, label, repolish, tile, hrule
from .base import Page, fill_combo

FIT_TEXT = {"good": ("Good fit", "good"), "stretch": ("Stretch", "warn"),
            "reach": ("Reach", "bad"), "over": ("Below your level", "warn")}
SORTS = [("Best match", "best"), ("Highest raw score", "raw"), ("Newest first", "new")]


def _badge_kind(score: float) -> str:
    return "good" if score >= 75 else "warn" if score >= 50 else "bad"


class JobRow(QFrame):
    clicked = Signal(int)

    def __init__(self, r: JobResult):
        super().__init__()
        self.job_id = r.job.job_id
        self.setProperty("role", "jobRow")
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)
        badge = QLabel(f"{r.adjusted:.0f}")
        badge.setProperty("badge", _badge_kind(r.adjusted))
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedWidth(48)
        badge.setToolTip("Match score adjusted for how well the role's seniority fits your experience")
        lay.addWidget(badge, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        t = label(r.job.job_title, "title")
        t.setWordWrap(True)
        col.addWidget(t)
        meta = " · ".join(x for x in (r.job.company_name, r.job.location, (r.job.work_mode or "").replace("_", " ").title() or None) if x)
        col.addWidget(label(meta, "muted", wrap=True))
        chips = QHBoxLayout()
        chips.setSpacing(6)
        if r.top_pick:
            chips.addWidget(chip("Top pick", "accent"))
        if r.fit_label in FIT_TEXT:
            txt, kind = FIT_TEXT[r.fit_label]
            chips.addWidget(chip(txt, kind))
        chips.addWidget(chip("AI checked" if r.verified else "Keyword score", "neutral"))
        chips.addStretch(1)
        col.addLayout(chips)
        src = r.job.source or ""
        more = f" +{len(r.job.also_on)}" if r.job.also_on else ""
        foot = label(f"via {src}{more}" + (f" · {r.job.posted_at:%d %b %Y}" if r.job.posted_at else "") + (f" · {r.job.salary}" if r.job.salary else ""), "small")
        col.addWidget(foot)
        lay.addLayout(col, 1)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        repolish(self)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.job_id)


class FindJobsPage(Page):
    title = "Find Jobs"
    subtitle = "Searches many job boards at once and puts the roles that best fit a candidate's skills and experience first."

    def __init__(self, ctx):
        super().__init__(ctx)
        self.results: list[JobResult] = []
        self.rows: dict[int, JobRow] = {}
        self.selected: Optional[int] = None
        self._match = None
        self._mode = ""

        # ---------------- search panel
        panel = tile()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(16, 14, 16, 14)
        pl.setSpacing(10)
        r1 = QHBoxLayout()
        r1.setSpacing(10)
        self.cand = QComboBox()
        self.cand.setMinimumWidth(200)
        self.cand.currentIndexChanged.connect(self._candidate_changed)
        self.roles = QLineEdit()
        self.roles.setPlaceholderText("Roles to look for, e.g. Data Engineer, ML Engineer (blank = from the resume)")
        self.location = QLineEdit()
        self.location.setPlaceholderText("City or country (optional)")
        self.location.setMaximumWidth(220)
        r1.addWidget(self.cand)
        r1.addWidget(self.roles, 1)
        r1.addWidget(self.location)
        pl.addLayout(r1)
        r2 = QHBoxLayout()
        r2.setSpacing(0)
        self.seg = QButtonGroup(self)
        self.seg.setExclusive(True)
        modes = [("Any", ""), ("Remote", "remote"), ("Hybrid", "hybrid"), ("On-site", "onsite")]
        for i, (text, val) in enumerate(modes):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("seg", "left" if i == 0 else "right" if i == len(modes) - 1 else "mid")
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(i == 0)
            b.clicked.connect(lambda _=False, v=val: setattr(self, "_mode", v))
            self.seg.addButton(b)
            r2.addWidget(b)
        r2.addStretch(1)
        self.roles_btn = button("Suggest roles", on_click=self.suggest_roles)
        self.search_btn = button("Search jobs", primary=True, on_click=self.search)
        self.search_btn.setIcon(icons.icon("search", "#FFFFFF", 16))
        r2.addWidget(self.roles_btn)
        r2.addSpacing(8)
        r2.addWidget(self.search_btn)
        pl.addLayout(r2)
        self.busy = BusyBar()
        pl.addWidget(self.busy)
        self.sources_row = QHBoxLayout()
        self.sources_row.setSpacing(6)
        pl.addLayout(self.sources_row)
        self.note = label("", "small", wrap=True)
        self.note.hide()
        pl.addWidget(self.note)
        self.root.addWidget(panel)

        # ---------------- filters
        fr = QHBoxLayout()
        fr.setSpacing(10)
        self.count = label("", "muted")
        fr.addWidget(self.count, 1)
        fr.addWidget(label("Min score", "muted"))
        self.min_score = QDoubleSpinBox()
        self.min_score.setRange(0, 100)
        self.min_score.setDecimals(0)
        self.min_score.setFixedWidth(64)
        self.min_score.valueChanged.connect(lambda *_: self._render_list())
        fr.addWidget(self.min_score)
        self.source = QComboBox()
        self.source.currentIndexChanged.connect(lambda *_: self._render_list())
        fr.addWidget(self.source)
        self.hide_reach = QCheckBox("Hide reach roles")
        self.hide_reach.toggled.connect(lambda *_: self._render_list())
        fr.addWidget(self.hide_reach)
        self.sort = QComboBox()
        for t, v in SORTS:
            self.sort.addItem(t, v)
        self.sort.currentIndexChanged.connect(lambda *_: self._render_list())
        fr.addWidget(self.sort)
        self.root.addLayout(fr)

        # ---------------- results + detail
        split = QSplitter(Qt.Horizontal)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.list_host = QWidget()
        self.list_host.setObjectName("page")
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 8, 0)
        self.list_lay.setSpacing(8)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(self.list_host)
        self.scroll.setMinimumWidth(400)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        split.addWidget(self.scroll)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        rl.setSpacing(10)
        self.d_title = label("", "detailTitle", wrap=True)
        self.d_meta = label("", "muted", wrap=True)
        rl.addWidget(self.d_title)
        rl.addWidget(self.d_meta)
        ar = QHBoxLayout()
        self.open_btn = button("Open job posting", primary=True, on_click=self.open_posting)
        self.open_btn.setIcon(icons.icon("external", "#FFFFFF", 16))
        self.verify_btn = button("Run AI analysis", on_click=self.verify_one)
        ar.addWidget(self.open_btn)
        ar.addWidget(self.verify_btn)
        ar.addStretch(1)
        rl.addLayout(ar)
        head = tile()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(16, 14, 16, 14)
        hl.setSpacing(18)
        self.ring = ScoreRing(112)
        hl.addWidget(self.ring)
        bars = QVBoxLayout()
        self.b_skill, self.b_exp, self.b_qual, self.b_sem = (
            MiniBar("Skills"), MiniBar("Experience"), MiniBar("Qualifications"), MiniBar("AI semantic fit"))
        for b in (self.b_skill, self.b_exp, self.b_qual, self.b_sem):
            bars.addWidget(b)
        hl.addLayout(bars, 1)
        rl.addWidget(head)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        rl.addWidget(self.view, 1)
        ov = QHBoxLayout()
        ov.setContentsMargins(0, 0, 0, 0)
        ov.addWidget(label("Reviewer override:", "muted"))
        self.ov_score = QDoubleSpinBox()
        self.ov_score.setRange(0, 100)
        self.ov_score.setDecimals(0)
        self.ov_note = QLineEdit()
        self.ov_note.setPlaceholderText("Reason (optional)")
        ov.addWidget(self.ov_score)
        ov.addWidget(self.ov_note, 1)
        ov.addWidget(button("Apply", on_click=self.apply_override))
        ov.addWidget(button("Clear", flat=True, on_click=self.clear_override))
        self.ov_box = QWidget()
        self.ov_box.setLayout(ov)
        rl.addWidget(self.ov_box)
        split.addWidget(right)
        split.setChildrenCollapsible(False)
        split.setSizes([470, 640])
        right.setMinimumWidth(380)
        self.root.addWidget(split, 1)
        self._show_detail(None)
        ctx.on_data_changed(self.refresh)

    # ------------------------------------------------------------------ lifecycle
    def apply_theme(self) -> None:
        c = self.ctx.colors
        self.ring.set_colors(c["border"], c["accent"], c["text"], c["muted"])
        self.search_btn.setIcon(icons.icon("search", c["accent_text"], 16))
        self.open_btn.setIcon(icons.icon("external", c["accent_text"], 16))
        self._render_detail()

    def refresh(self) -> None:
        core = self.ctx.core
        fill_combo(self.cand, [(f"{c.candidate_name}  (#{c.candidate_id})", c.candidate_id) for c in core.list_candidates()],
                   "Select a candidate...")
        if self.cand.currentIndex() <= 0 and self.cand.count() > 1:
            self.cand.setCurrentIndex(1)
        ready = sum(1 for p in core.providers if core.provider_state(p) == "ready")
        if not self.sources_row.count():
            self._show_sources(None)
        self.search_btn.setToolTip(f"{ready} of {len(core.providers)} job sources ready")

    def _candidate_changed(self) -> None:
        cid = self.cand.currentData()
        self.results = []
        if cid is not None:
            cand = self.ctx.core.get_candidate(cid)
            self.roles.setText(cand.preferred_roles or "")
            self.location.setText(cand.preferred_location or "")
            self._mode = cand.work_mode_pref or ""
            for b, v in zip(self.seg.buttons(), ("", "remote", "hybrid", "onsite")):
                b.setChecked(v == self._mode)
            self.results = self.ctx.core.latest_job_results(cid)
        self.selected = None
        self._fill_sources()
        self._render_list()

    # ------------------------------------------------------------------ search
    def search(self) -> None:
        cid = self.cand.currentData()
        if cid is None:
            self.ctx.info("Select a candidate", "Choose a candidate whose resume has been analysed first.")
            return
        roles, loc, mode = self.roles.text(), self.location.text(), self._mode
        verify = self.ctx.core.ai.is_configured()
        if verify and not self.ctx.ensure_ai_ready():
            verify = False

        def done(out: SearchOutcome):
            self.results = out.results
            self.selected = None
            self._show_sources(out)
            self.note.setText(("Searched for: " + ", ".join(out.queries) + ". ") + (out.ai_note or ""))
            self.note.show()
            self._fill_sources()
            self._render_list()
            self.ctx.status(f"Found {out.found} jobs")

        self.busy.start("Searching job boards...")
        self.ctx.run(
            lambda progress: self.ctx.core.search_jobs(cid, roles, loc, mode, progress=progress, verify=verify),
            done,
            on_progress=lambda c, t, m: self.busy.update_progress(c, t, m) if t else self.busy.caption.setText(m),
            busy=lambda b: (self.search_btn.setEnabled(not b), None if b else self.busy.stop()),
        )

    def suggest_roles(self) -> None:
        cid = self.cand.currentData()
        if cid is None:
            self.ctx.info("Select a candidate", "Choose a candidate first.")
            return
        if not self.ctx.ensure_ai_ready():
            return
        mode = self._mode

        def done(res):
            menu = QMenu(self)
            for r in res.roles[:8]:
                a = menu.addAction(f"{r.title}")
                a.triggered.connect(lambda _=False, t=r.title: self._add_role(t))
            menu.exec(self.roles_btn.mapToGlobal(self.roles_btn.rect().bottomLeft()))

        self.busy.start("Asking Gemini for suitable roles...")
        self.ctx.run(lambda: self.ctx.core.suggest_roles(cid, {"work_mode": mode}), done,
                     busy=lambda b: (self.roles_btn.setEnabled(not b), None if b else self.busy.stop()))

    def _add_role(self, title: str) -> None:
        cur = [x.strip() for x in self.roles.text().split(",") if x.strip()]
        if title not in cur:
            cur.append(title)
        self.roles.setText(", ".join(cur))

    # ------------------------------------------------------------------ source chips
    def _show_sources(self, out: Optional[SearchOutcome]) -> None:
        while self.sources_row.count():
            it = self.sources_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if out is None:
            ready = [p for p in self.ctx.core.providers if self.ctx.core.provider_state(p) == "ready"]
            self.sources_row.addWidget(chip(f"{len(ready)} job sources ready", "neutral"))
            need = len(self.ctx.core.providers) - len(ready)
            if need:
                self.sources_row.addWidget(label(f"{need} more can be switched on in Settings (some need a free API key).", "small"))
            self.sources_row.addStretch(1)
            return
        for s in out.sources:
            if s.skipped:
                c = chip(f"{s.label}: {s.skipped.lower()}", "neutral")
            elif s.error:
                c = chip(f"{s.label}: failed", "bad")
                c.setToolTip(s.error)
            else:
                c = chip(f"{s.label} {s.count}" + (" (cached)" if s.cached else ""), "good" if s.count else "neutral")
            self.sources_row.addWidget(c)
        self.sources_row.addStretch(1)

    def _fill_sources(self) -> None:
        cur = self.source.currentData()
        names = sorted({r.job.source for r in self.results if r.job.source})
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItem("All sources", None)
        for n in names:
            self.source.addItem(n, n)
        i = self.source.findData(cur)
        self.source.setCurrentIndex(i if i >= 0 else 0)
        self.source.blockSignals(False)

    # ------------------------------------------------------------------ list
    def _visible(self) -> list[JobResult]:
        src, floor, hide = self.source.currentData(), self.min_score.value(), self.hide_reach.isChecked()
        out = [r for r in self.results if r.adjusted >= floor and (src is None or r.job.source == src)
               and not (hide and r.fit_label == "reach")]
        key = self.sort.currentData()
        if key == "raw":
            out.sort(key=lambda r: -(r.match.final_score or 0))
        elif key == "new":
            out.sort(key=lambda r: -(r.job.posted_at.timestamp() if r.job.posted_at else 0))
        else:
            out.sort(key=lambda r: r.rank)
        return out

    def _render_list(self) -> None:
        while self.list_lay.count() > 1:
            it = self.list_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.rows = {}
        vis = self._visible()
        if not vis:
            msg = ("Press Search jobs to find roles that fit this candidate." if not self.results
                   else "No jobs match the current filters.")
            self.list_lay.insertWidget(0, label(msg, "muted", wrap=True))
        for i, r in enumerate(vis):
            row = JobRow(r)
            row.clicked.connect(self._select)
            self.rows[r.job.job_id] = row
            self.list_lay.insertWidget(i, row)
        self.count.setText(f"{len(vis)} of {len(self.results)} jobs" if self.results else "")
        if vis:
            ids = [r.job.job_id for r in vis]
            self._select(self.selected if self.selected in ids else ids[0])
        else:
            self._show_detail(None)

    def _select(self, job_id: int) -> None:
        self.selected = job_id
        for jid, row in self.rows.items():
            row.set_selected(jid == job_id)
        self._show_detail(next((r for r in self.results if r.job.job_id == job_id), None))

    # ------------------------------------------------------------------ detail
    def _current(self) -> Optional[JobResult]:
        return next((r for r in self.results if r.job.job_id == self.selected), None)

    def _show_detail(self, r: Optional[JobResult]) -> None:
        self._match = r.match if r else None
        self._render_detail()

    def _render_detail(self) -> None:
        r = self._current() if self.selected is not None else None
        col = self.ctx.colors
        has = r is not None
        for w in (self.open_btn, self.verify_btn, self.ov_box):
            w.setEnabled(has)
        if not has:
            self.d_title.setText("No job selected")
            self.d_meta.setText("")
            self.ring.set_score(None)
            for b in (self.b_skill, self.b_exp, self.b_qual, self.b_sem):
                b.set_value(None)
            self.view.setHtml(f"<p style='color:{col['muted']}'>Search for jobs, then pick one to see why it fits.</p>")
            return
        m, j = r.match, r.job
        d = m.details or {}
        self.d_title.setText(j.job_title)
        self.d_meta.setText(" · ".join(x for x in (j.company_name, j.location, j.salary, j.employment_type, f"via {j.source}") if x))
        self.verify_btn.setVisible(not r.verified)
        self.ring.set_score(r.adjusted, score_color(r.adjusted, col))
        self.b_skill.set_value(m.skill_score)
        self.b_exp.set_value(m.experience_score)
        self.b_qual.set_value(m.qualification_score)
        self.b_sem.set_value(m.semantic_score)
        self.ov_score.setValue(m.override_score if m.override_score is not None else round(r.adjusted))
        self.ov_note.setText(m.override_note or "")

        def bullets(items):
            return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>" if items else f"<p style='color:{col['muted']}'>None</p>"

        h = []
        if m.override_score is not None:
            h.append(f"<p><b>Reviewer override:</b> {m.override_score:.0f} (automated {m.overall_score:.0f})"
                     + (f" - {esc(m.override_note)}" if m.override_note else "") + "</p>")
        if r.fit_text:
            h.append(f"<p><b>Experience fit:</b> {esc(r.fit_text)}"
                     + (f" <span style='color:{col['muted']}'>(score adjusted by -{r.penalty:.0f})</span>" if r.penalty else "") + "</p>")
        if not r.verified:
            h.append(f"<p style='color:{col['muted']}'>This is a quick keyword-based score. Use <b>Run AI analysis</b> for a deeper check.</p>")
        h.append(f"<h3>Why this score</h3><p>{esc(m.analysis_explanation or '')}</p>")
        h.append("<h3>Matching skills</h3><p>" + chips_html(d.get("matched_skills", []), col["good"], col["good_bg"]) + "</p>")
        h.append("<h3>Skills to build</h3><p>" + chips_html(d.get("missing_skills", []), col["bad"], col["bad_bg"]) + "</p>")
        if r.verified:
            h.append("<h3>Strengths</h3>" + bullets(d.get("strengths", [])))
            h.append("<h3>Potential concerns</h3>" + bullets(d.get("concerns", [])))
        h.append("<h3>Missing or uncertain information</h3>" + bullets(d.get("uncertainties", [])))
        self.view.setHtml("".join(h))

    # ------------------------------------------------------------------ actions
    def open_posting(self) -> None:
        r = self._current()
        if r and r.job.url and r.job.url.lower().startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(r.job.url))

    def verify_one(self) -> None:
        r, cid = self._current(), self.cand.currentData()
        if r is None or cid is None or not self.ctx.ensure_ai_ready():
            return
        jid = r.job.job_id

        def done(new: JobResult):
            self.results = [new if x.job.job_id == jid else x for x in self.results]
            self.results = self.ctx.core._rank_results(self.results)
            self._render_list()

        self.busy.start("Analysing with Gemini...")
        self.ctx.run(lambda: self.ctx.core.analyse_job_for(cid, jid), done,
                     busy=lambda b: (self.verify_btn.setEnabled(not b), None if b else self.busy.stop()))

    def _reload_result(self, m) -> None:
        r = self._current()
        if r:
            new = self.ctx.core._to_result(r.job, m)
            self.results = self.ctx.core._rank_results([new if x.job.job_id == r.job.job_id else x for x in self.results])
            self._render_list()

    def apply_override(self) -> None:
        r = self._current()
        if r:
            self._reload_result(self.ctx.core.set_override(r.match.match_id, self.ov_score.value(), self.ov_note.text()))

    def clear_override(self) -> None:
        r = self._current()
        if r:
            self._reload_result(self.ctx.core.set_override(r.match.match_id, None))
