"""Main window: sidebar navigation + stacked pages."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from ..services import Core
from . import icons, theme
from .context import AppContext
from .pages.dashboard import DashboardPage
from .pages.find_jobs import FindJobsPage
from .pages.ranking import RankingPage
from .pages.reports_page import ReportsPage
from .pages.resume_analyzer import ResumeAnalyzerPage
from .pages.settings_page import SettingsPage
from .pages.skill_gap import SkillGapPage

NAV = [
    ("dashboard", "Dashboard", "dashboard"),
    ("resume", "Resume Analyzer", "resume"),
    ("find", "Find Jobs", "search"),
    ("ranking", "Candidate Ranking", "ranking"),
    ("gap", "Skill Gap Analyzer", "gap"),
    ("reports", "Reports", "reports"),
    ("settings", "Settings", "settings"),
]


class MainWindow(QMainWindow):
    def __init__(self, core: Core):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.setMinimumSize(980, 640)
        self.core = core
        self.ctx = AppContext(core, self)
        self._asset_dir = Path(tempfile.mkdtemp(prefix="rm_assets_"))

        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(232)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 18, 0, 12)
        sl.setSpacing(0)
        brand = QLabel(APP_NAME)
        brand.setObjectName("brand")
        brand.setContentsMargins(20, 0, 0, 0)
        sub = QLabel("AI recruitment assistant")
        sub.setObjectName("brandSub")
        sub.setContentsMargins(20, 0, 0, 14)
        sl.addWidget(brand)
        sl.addWidget(sub)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFocusPolicy(Qt.TabFocus)
        for key, text, _ic in NAV:
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, key)
            self.nav.addItem(it)
        sl.addWidget(self.nav, 1)
        foot = QLabel(f"v{__version__}")
        foot.setObjectName("sideFoot")
        foot.setContentsMargins(20, 0, 0, 0)
        sl.addWidget(foot)
        outer.addWidget(side)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.pages = {
            "dashboard": DashboardPage(self.ctx, self.go),
            "resume": ResumeAnalyzerPage(self.ctx),
            "find": FindJobsPage(self.ctx),
            "ranking": RankingPage(self.ctx),
            "gap": SkillGapPage(self.ctx),
            "reports": ReportsPage(self.ctx),
            "settings": SettingsPage(self.ctx, self.apply_theme),
        }
        for key, _t, _i in NAV:
            self.stack.addWidget(self.pages[key])
        self.ctx.set_status_sink(lambda m: self.statusBar().showMessage(m, 8000))
        self.statusBar().showMessage("Ready")

        self.nav.currentRowChanged.connect(self._nav_changed)
        self.nav.currentRowChanged.connect(lambda _r: self._recolor_nav())
        self.apply_theme()
        self.ctx.data_changed()
        self.pages["settings"].refresh()
        self.nav.setCurrentRow(0)

    # ------------------------------------------------------------------
    def go(self, key: str) -> None:
        for i, (k, _t, _i) in enumerate(NAV):
            if k == key:
                self.nav.setCurrentRow(i)
                return

    def _nav_changed(self, row: int) -> None:
        if row < 0:
            return
        key = NAV[row][0]
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        page.refresh()

    def apply_theme(self) -> None:
        name = self.core.settings.settings.theme
        c = theme.PALETTES[name]
        chevron = icons.write_png("chevron", c["muted"], self._asset_dir / f"chevron_{name}.png")
        check = icons.write_png("check", c["accent_text"], self._asset_dir / f"check_{name}.png")
        QApplication.instance().setStyleSheet(theme.build_qss(name, chevron, check))
        for i, (_k, _t, ic) in enumerate(NAV):
            color = c["accent"] if i == self.nav.currentRow() else c["muted"]
            self.nav.item(i).setIcon(icons.icon(ic, color, 20))
        for page in self.pages.values():
            page.apply_theme()

    def _recolor_nav(self) -> None:
        c = self.ctx.colors
        for i, (_k, _t, ic) in enumerate(NAV):
            self.nav.item(i).setIcon(icons.icon(ic, c["accent"] if i == self.nav.currentRow() else c["muted"], 20))

    def closeEvent(self, event) -> None:  # noqa: N802
        self.core.close()
        super().closeEvent(event)
