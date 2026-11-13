"""Reusable UI building blocks."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Callable, Iterable, Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..parsing import SUPPORTED_EXTENSIONS
from . import icons

esc = html.escape


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


def label(text: str = "", role: str = "", wrap: bool = False, selectable: bool = False) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    if selectable:
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


def chip(text: str, kind: str = "neutral") -> QLabel:
    lb = QLabel(text)
    lb.setProperty("chip", kind)
    lb.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lb


def button(text: str, primary: bool = False, danger: bool = False, flat: bool = False,
           on_click: Optional[Callable[[], None]] = None) -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setProperty("primary", True)
    if danger:
        b.setProperty("danger", True)
    if flat:
        b.setProperty("flat", True)
    b.setCursor(Qt.PointingHandCursor)
    if on_click:
        b.clicked.connect(lambda _=False: on_click())
    return b


def hrule() -> QFrame:
    f = QFrame()
    f.setProperty("role", "rule")
    f.setFrameShape(QFrame.NoFrame)
    return f


def tile() -> QFrame:
    f = QFrame()
    f.setProperty("role", "tile")
    return f


def banner(text: str, kind: str = "banner") -> QFrame:
    f = QFrame()
    f.setProperty("role", kind)
    lay = QHBoxLayout(f)
    lay.setContentsMargins(12, 8, 12, 8)
    lb = QLabel(text)
    lb.setWordWrap(True)
    lay.addWidget(lb)
    return f


class StatTile(QFrame):
    def __init__(self, caption: str):
        super().__init__()
        self.setProperty("role", "tile")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(2)
        self.value = label("-", "stat")
        self.caption = label(caption, "muted")
        lay.addWidget(self.value)
        lay.addWidget(self.caption)

    def set_value(self, text: str) -> None:
        self.value.setText(text)


class ScoreRing(QWidget):
    """Circular gauge for the 0-100 compatibility score."""

    def __init__(self, size: int = 128):
        super().__init__()
        self._score: Optional[float] = None
        self._track = QColor("#ccc")
        self._fg = QColor("#2457D6")
        self._text = QColor("#000")
        self._muted = QColor("#666")
        self.setFixedSize(size, size)

    def set_colors(self, track: str, fg: str, text: str, muted: str) -> None:
        self._track, self._fg, self._text, self._muted = QColor(track), QColor(fg), QColor(text), QColor(muted)
        self.update()

    def set_score(self, score: Optional[float], fg: Optional[str] = None) -> None:
        self._score = score
        if fg:
            self._fg = QColor(fg)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = 10
        r = QRectF(w, w, self.width() - 2 * w, self.height() - 2 * w)
        pen = QPen(self._track, w, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(r, 0, 360 * 16)
        if self._score is not None:
            pen.setColor(self._fg)
            p.setPen(pen)
            p.drawArc(r, 90 * 16, int(-360 * 16 * max(0.0, min(100.0, self._score)) / 100))
        p.setPen(self._text)
        f = p.font()
        f.setPointSize(26)
        f.setBold(True)
        p.setFont(f)
        p.drawText(self.rect().adjusted(0, -8, 0, -8), Qt.AlignCenter, "-" if self._score is None else f"{self._score:.0f}")
        f.setPointSize(9)
        f.setBold(False)
        p.setFont(f)
        p.setPen(self._muted)
        p.drawText(self.rect().adjusted(0, 40, 0, 0), Qt.AlignHCenter | Qt.AlignVCenter, "out of 100")


class MiniBar(QWidget):
    """Labelled horizontal bar for sub-scores."""

    def __init__(self, caption: str):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        self.caption = label(caption)
        self.caption.setFixedWidth(110)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.value = label("n/a", "muted")
        self.value.setFixedWidth(46)
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.caption)
        lay.addWidget(self.bar, 1)
        lay.addWidget(self.value)

    def set_value(self, v: Optional[float]) -> None:
        if v is None:
            self.bar.setValue(0)
            self.value.setText("n/a")
        else:
            self.bar.setValue(int(round(v)))
            self.value.setText(f"{v:.0f}")


class DropZone(QFrame):
    """Drag-and-drop target with a browse button."""

    files_selected = Signal(list)

    def __init__(self, title: str, hint: str, filters: str, multiple: bool = True,
                 extensions: Iterable[str] = SUPPORTED_EXTENSIONS):
        super().__init__()
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self._filters, self._multiple = filters, multiple
        self._exts = tuple(e.lower() for e in extensions)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 22, 20, 22)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignCenter)
        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignCenter)
        self.title = label(title, "h2")
        self.title.setAlignment(Qt.AlignCenter)
        self.hint = label(hint, "muted", wrap=True)
        self.hint.setAlignment(Qt.AlignCenter)
        self.btn = button("Browse files...", primary=True, on_click=self._browse)
        lay.addWidget(self.icon)
        lay.addWidget(self.title)
        lay.addWidget(self.hint)
        lay.addSpacing(4)
        lay.addWidget(self.btn, 0, Qt.AlignCenter)

    def set_icon_color(self, color: str) -> None:
        self.icon.setPixmap(icons.pixmap("upload", color, 34))

    def _browse(self) -> None:
        if self._multiple:
            paths, _ = QFileDialog.getOpenFileNames(self, "Select files", str(Path.home()), self._filters)
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Select file", str(Path.home()), self._filters)
            paths = [p] if p else []
        if paths:
            self.files_selected.emit(paths)

    def _set_hover(self, on: bool) -> None:
        self.setProperty("hover", on)
        repolish(self)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._set_hover(True)

    def dragLeaveEvent(self, _e) -> None:
        self._set_hover(False)

    def dropEvent(self, e) -> None:
        self._set_hover(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if not self._multiple:
            paths = paths[:1]
        if paths:
            self.files_selected.emit(paths)

    def set_busy(self, busy: bool) -> None:
        self.setEnabled(not busy)


class BusyBar(QWidget):
    """Progress bar + caption that stays hidden until needed."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.caption = label("", "small")
        self.bar = QProgressBar()
        self.bar.setFixedHeight(8)
        lay.addWidget(self.caption)
        lay.addWidget(self.bar)
        self.hide()

    def start(self, text: str, total: int = 0) -> None:
        self.caption.setText(text)
        self.bar.setRange(0, total)  # total == 0 -> indeterminate
        self.bar.setValue(0)
        self.show()

    def update_progress(self, cur: int, total: int, msg: str = "") -> None:
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(cur)
        self.caption.setText(f"{msg}  ({cur}/{total})" if msg else f"{cur}/{total}")

    def stop(self) -> None:
        self.hide()


class NumItem(QTableWidgetItem):
    """Table item that sorts numerically."""

    def __init__(self, value: Optional[float], text: Optional[str] = None):
        super().__init__(text if text is not None else ("n/a" if value is None else f"{value:.1f}"))
        self._v = -1.0 if value is None else float(value)
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other) -> bool:  # type: ignore[override]
        return self._v < getattr(other, "_v", -1.0)


def make_table(headers: list[str], stretch_col: Optional[int] = None) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.setSelectionMode(QTableWidget.SingleSelection)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setShowGrid(False)
    t.setSortingEnabled(False)
    t.horizontalHeader().setHighlightSections(False)
    t.horizontalHeader().setStretchLastSection(stretch_col is None)
    if stretch_col is not None:
        from PySide6.QtWidgets import QHeaderView

        t.horizontalHeader().setSectionResizeMode(stretch_col, QHeaderView.Stretch)
    t.verticalHeader().setDefaultSectionSize(34)
    return t


def chips_html(items: list[str], color: str, bg: str) -> str:
    if not items:
        return "<span style='opacity:.65'>None</span>"
    return " ".join(
        f"<span style='background:{bg}; color:{color}; padding:2px 8px; border-radius:9px;'>&nbsp;{esc(i)}&nbsp;</span>"
        for i in items
    )
