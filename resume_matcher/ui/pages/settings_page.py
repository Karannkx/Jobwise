from __future__ import annotations

import os
import platform
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLineEdit, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ... import APP_NAME, AUTHORS, __version__
from ...jobsearch import ADZUNA_COUNTRIES, COUNTRY_NAMES
from ...config import API_KEY_ENV, DEFAULT_MODEL, ScoringWeights
from ..widgets import BusyBar, banner, button, chip, hrule, label, tile
from .base import Page

MODELS = ["gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]


class SettingsPage(Page):
    title = "Settings"
    subtitle = "Gemini API, appearance, scoring weights and local data."

    def __init__(self, ctx, on_theme_changed):
        super().__init__(ctx)
        self.on_theme_changed = on_theme_changed
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        body.setObjectName("page")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(14)

        # --- Gemini
        lay.addWidget(label("GEMINI API", "section"))
        box = tile()
        f = QFormLayout(box)
        f.setContentsMargins(16, 14, 16, 14)
        f.setVerticalSpacing(10)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Paste your API key")
        self.key_state = chip("", "neutral")
        keyrow = QHBoxLayout()
        keyrow.addWidget(self.key, 1)
        keyrow.addWidget(button("Show", flat=True, on_click=self._toggle_key))
        f.addRow("API key", keyrow)
        f.addRow("", self.key_state)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems(MODELS)
        f.addRow("Model", self.model)
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 300)
        self.timeout.setSuffix(" s")
        self.retries = QSpinBox()
        self.retries.setRange(0, 8)
        f.addRow("Request timeout", self.timeout)
        f.addRow("Max retries", self.retries)
        btns = QHBoxLayout()
        self.save_btn = button("Save", primary=True, on_click=self.save_api)
        self.test_btn = button("Test connection", on_click=self.test)
        btns.addWidget(self.save_btn)
        btns.addWidget(self.test_btn)
        btns.addWidget(button("Remove saved key", danger=True, on_click=self.remove_key))
        btns.addStretch(1)
        f.addRow("", btns)
        self.busy = BusyBar()
        f.addRow("", self.busy)
        lay.addWidget(box)
        lay.addWidget(banner(
            f"The key is read from the {API_KEY_ENV} environment variable first, otherwise from an owner-only file in the "
            "application data folder. It is never written to the database, reports or logs.", "info"))

        # --- job sources
        lay.addWidget(label("JOB SOURCES", "section"))
        box_js = tile()
        vj = QVBoxLayout(box_js)
        vj.setContentsMargins(16, 14, 16, 14)
        vj.setSpacing(10)
        vj.addWidget(label("Find Jobs searches every source that is switched on. Sources marked 'key' need a free API key "
                           "from the provider; they are skipped until you add one. Keys are stored only on this computer.",
                           "muted", wrap=True))
        gf = QFormLayout()
        gf.setVerticalSpacing(8)
        self.country = QComboBox()
        for code in ADZUNA_COUNTRIES:
            self.country.addItem(COUNTRY_NAMES.get(code, code.upper()), code)
        self.verify_top = QSpinBox()
        self.verify_top.setRange(0, 30)
        self.verify_top.setToolTip("How many of the best results Gemini double-checks. 0 = keyword scores only.")
        self.max_age = QSpinBox()
        self.max_age.setRange(1, 365)
        self.max_age.setSuffix(" days")
        self.per_source = QSpinBox()
        self.per_source.setRange(5, 100)
        gf.addRow("Search country", self.country)
        gf.addRow("AI-verify top results", self.verify_top)
        gf.addRow("Ignore jobs older than", self.max_age)
        gf.addRow("Results per source", self.per_source)
        vj.addLayout(gf)
        vj.addWidget(hrule())
        self.prov_rows: dict[str, dict] = {}
        for p in ctx.core.providers:
            top = QHBoxLayout()
            en = QCheckBox(p.label)
            en.setStyleSheet("font-weight: 600;")
            top.addWidget(en)
            if p.needs_key:
                top.addWidget(chip("key", "warn"))
            top.addWidget(chip(p.region, "neutral"))
            state = chip("", "neutral")
            top.addWidget(state)
            top.addStretch(1)
            top.addWidget(button("Website", flat=True, on_click=lambda _h=p.homepage: QDesktopServices.openUrl(QUrl(_h))))
            vj.addLayout(top)
            vj.addWidget(label(p.description, "small", wrap=True))
            edits: dict[str, QLineEdit] = {}
            for fld in p.fields:
                e = QLineEdit()
                e.setEchoMode(QLineEdit.Password if fld.secret else QLineEdit.Normal)
                e.setPlaceholderText(f"{fld.label}  (or set {fld.env})")
                vj.addWidget(e)
                edits[fld.id] = e
            self.prov_rows[p.id] = {"enable": en, "state": state, "edits": edits}
        jb = QHBoxLayout()
        jb.addWidget(button("Save job sources", primary=True, on_click=self.save_sources))
        jb.addWidget(button("Clear found jobs", danger=True, on_click=self.clear_found))
        jb.addStretch(1)
        vj.addLayout(jb)
        lay.addWidget(box_js)

        # --- appearance
        lay.addWidget(label("APPEARANCE", "section"))
        box2 = tile()
        f2 = QFormLayout(box2)
        f2.setContentsMargins(16, 14, 16, 14)
        self.theme = QComboBox()
        self.theme.addItem("Light", "light")
        self.theme.addItem("Dark", "dark")
        self.theme.currentIndexChanged.connect(self._theme_changed)
        f2.addRow("Theme", self.theme)
        lay.addWidget(box2)

        # --- scoring
        lay.addWidget(label("SCORING WEIGHTS", "section"))
        box3 = tile()
        f3 = QFormLayout(box3)
        f3.setContentsMargins(16, 14, 16, 14)
        self.w = {}
        for key, text in (("skills", "Skill coverage"), ("experience", "Experience"),
                          ("qualification", "Qualifications"), ("semantic", "AI semantic fit")):
            sp = QDoubleSpinBox()
            sp.setRange(0, 100)
            sp.setDecimals(0)
            sp.setSuffix(" %")
            self.w[key] = sp
            f3.addRow(text, sp)
        wb = QHBoxLayout()
        wb.addWidget(button("Save weights", on_click=self.save_weights))
        wb.addWidget(button("Reset to defaults", flat=True, on_click=self.reset_weights))
        wb.addStretch(1)
        f3.addRow("", wb)
        f3.addRow("", label("Weights are normalised to 100%. The AI score is only one input; structured skill, experience and "
                            "qualification scores are computed locally.", "small", wrap=True))
        lay.addWidget(box3)

        # --- data
        lay.addWidget(label("DATA MANAGEMENT", "section"))
        box4 = tile()
        v4 = QVBoxLayout(box4)
        v4.setContentsMargins(16, 14, 16, 14)
        self.path_lbl = label("", "muted", wrap=True, selectable=True)
        v4.addWidget(self.path_lbl)
        r = QHBoxLayout()
        r.addWidget(button("Open data folder", on_click=self.open_folder))
        r.addWidget(button("Clear AI cache", on_click=self.clear_cache))
        r.addWidget(button("Delete all candidates and jobs", danger=True, on_click=self.delete_all))
        r.addStretch(1)
        v4.addLayout(r)
        lay.addWidget(box4)

        # --- about
        lay.addWidget(label("ABOUT", "section"))
        box5 = tile()
        v5 = QVBoxLayout(box5)
        v5.setContentsMargins(16, 14, 16, 14)
        v5.addWidget(label(f"{APP_NAME} {__version__}", "h2"))
        v5.addWidget(label("AI-powered resume parsing, job matching, candidate ranking and skill-gap analysis.", "muted", wrap=True))
        v5.addWidget(label(f"Created by {AUTHORS}", "muted"))
        v5.addWidget(label(f"Python {platform.python_version()} on {platform.system()}", "small"))
        v5.addWidget(hrule())
        v5.addWidget(label("AI results are decision support, not hiring decisions. AI cannot eliminate bias completely; "
                           "protected characteristics are excluded from scoring and a person should review every result.",
                           "small", wrap=True))
        lay.addWidget(box5)
        lay.addStretch(1)
        scroll.setWidget(body)
        self.root.addWidget(scroll, 1)
        self._loading = False

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        s = self.ctx.core.settings.settings
        self._loading = True
        self.model.setCurrentText(s.model)
        self.timeout.setValue(s.request_timeout_seconds)
        self.retries.setValue(s.max_retries)
        self.theme.setCurrentIndex(self.theme.findData(s.theme))
        for k, sp in self.w.items():
            sp.setValue(round(getattr(s.weights, k) * 100))
        i = self.country.findData(s.search_country)
        self.country.setCurrentIndex(max(i, 0))
        self.verify_top.setValue(s.ai_verify_top)
        self.max_age.setValue(s.max_job_age_days)
        self.per_source.setValue(s.per_source_limit)
        self._source_state()
        self.path_lbl.setText(f"Data folder: {self.ctx.core.home}")
        self.key.clear()
        self._key_status()
        self._loading = False

    def _key_status(self) -> None:
        src = self.ctx.core.settings.api_key_source()
        text = {"environment": f"Using {API_KEY_ENV} environment variable", "settings": "Key saved in settings", None: "No key configured"}[src]
        self.key_state.setText(text)
        self.key_state.setProperty("chip", "good" if src else "warn")
        self.key_state.style().unpolish(self.key_state)
        self.key_state.style().polish(self.key_state)

    def _source_state(self) -> None:
        core = self.ctx.core
        off = set(core.settings.settings.disabled_sources)
        for p in core.providers:
            row = self.prov_rows[p.id]
            row["enable"].setChecked(p.id not in off)
            for fid, e in row["edits"].items():
                e.clear()
            st = core.provider_state(p)
            src = [core.settings.credential_source(p.id, f.id, f.env) for f in p.fields]
            text = {"disabled": "off", "needs_key": "needs key", "ready": "ready"}[st]
            if st == "ready" and p.needs_key and "environment" in src:
                text = "ready (env)"
            row["state"].setText(text)
            row["state"].setProperty("chip", {"disabled": "neutral", "needs_key": "warn", "ready": "good"}[st])
            row["state"].style().unpolish(row["state"])
            row["state"].style().polish(row["state"])

    def save_sources(self) -> None:
        st = self.ctx.core.settings
        try:
            disabled = [pid for pid, r in self.prov_rows.items() if not r["enable"].isChecked()]
            for pid, r in self.prov_rows.items():
                vals = {fid: e.text().strip() for fid, e in r["edits"].items() if e.text().strip()}
                if vals:
                    st.set_credentials(pid, vals)
            st.update(disabled_sources=disabled, search_country=self.country.currentData(),
                      ai_verify_top=self.verify_top.value(), max_job_age_days=self.max_age.value(),
                      per_source_limit=self.per_source.value())
        except Exception as exc:  # noqa: BLE001
            self.ctx.show_error(exc)
            return
        self._source_state()
        self.ctx.status("Job sources saved")
        self.ctx.data_changed()

    def clear_found(self) -> None:
        if self.ctx.confirm("Clear found jobs", "Delete all jobs found by searches (and their match scores)?", danger=True):
            n = self.ctx.core.clear_found_jobs()
            self.ctx.status(f"Removed {n} found job(s)")
            self.ctx.data_changed()

    def _toggle_key(self) -> None:
        self.key.setEchoMode(QLineEdit.Normal if self.key.echoMode() == QLineEdit.Password else QLineEdit.Password)

    def save_api(self) -> None:
        st = self.ctx.core.settings
        try:
            if self.key.text().strip():
                st.set_api_key(self.key.text())
            st.update(model=self.model.currentText(), request_timeout_seconds=self.timeout.value(),
                      max_retries=self.retries.value())
        except Exception as exc:  # noqa: BLE001
            self.ctx.show_error(exc)
            return
        self.key.clear()
        self._key_status()
        self.ctx.status("Settings saved")
        self.ctx.data_changed()

    def remove_key(self) -> None:
        if self.ctx.confirm("Remove key", "Remove the saved API key from this computer?"):
            self.ctx.core.settings.set_api_key("")
            self._key_status()
            self.ctx.data_changed()

    def test(self) -> None:
        self.save_api()
        if not self.ctx.core.ai.is_configured():
            self.ctx.ensure_ai_ready()  # shows the "no key" message
            return
        self.busy.start("Contacting Gemini...")
        self.ctx.run(self.ctx.core.ai.test_connection,
                     lambda _r: self.ctx.info("Connection OK", "Gemini accepted the API key and responded."),
                     busy=lambda b: (self.test_btn.setEnabled(not b), None if b else self.busy.stop()))

    def _theme_changed(self) -> None:
        if self._loading:
            return
        self.ctx.core.settings.update(theme=self.theme.currentData())
        self.on_theme_changed()

    def save_weights(self) -> None:
        vals = {k: sp.value() / 100 for k, sp in self.w.items()}
        if sum(vals.values()) <= 0:
            self.ctx.info("Invalid weights", "At least one weight must be above zero.")
            return
        self.ctx.core.settings.update(weights=ScoringWeights(**vals).model_dump())
        self.ctx.status("Scoring weights saved. Re-run analyses to apply them.")

    def reset_weights(self) -> None:
        d = ScoringWeights()
        for k, sp in self.w.items():
            sp.setValue(round(getattr(d, k) * 100))
        self.save_weights()

    def open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.core.home)))

    def clear_cache(self) -> None:
        n = self.ctx.core.clear_ai_cache()
        self.ctx.status(f"Cleared {n} cached AI response(s)")

    def delete_all(self) -> None:
        if self.ctx.confirm("Delete all data",
                            "Delete ALL candidates, resume files, jobs and analyses from this computer? This cannot be undone.",
                            danger=True):
            self.ctx.core.delete_all_data()
            self.ctx.status("All candidate and job data deleted")
            self.ctx.data_changed()
