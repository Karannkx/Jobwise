"""Light / dark palettes and the application style sheet."""

from __future__ import annotations

from pathlib import Path
from string import Template

PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#F7F8FA", "surface": "#FFFFFF", "surface2": "#F0F2F5", "text": "#14181F",
        "muted": "#5B6472", "accent": "#3B5BDB", "accent_hover": "#2F49B5", "accent_text": "#FFFFFF",
        "border": "#E1E5EB", "good": "#13693F", "good_bg": "#E4F3EA", "warn": "#8A5300",
        "warn_bg": "#FFF3DC", "bad": "#B1261E", "bad_bg": "#FCE9E7", "sel": "#E6EBFB",
        "nav_bg": "#FFFFFF", "nav_sel": "#EDF0FC", "disabled": "#9AA3B2",
    },
    "dark": {
        "bg": "#101319", "surface": "#171B22", "surface2": "#1E232C", "text": "#E8EBF0",
        "muted": "#9AA3B2", "accent": "#8DA4FF", "accent_hover": "#A9BAFF", "accent_text": "#0B1226",
        "border": "#2A303B", "good": "#5FD39A", "good_bg": "#173226", "warn": "#F0B052",
        "warn_bg": "#352A14", "bad": "#FF8F86", "bad_bg": "#3A1D1B", "sel": "#222B45",
        "nav_bg": "#13171D", "nav_sel": "#1F2740", "disabled": "#5F6877",
    },
}

FONT_STACK = "'Inter', 'Segoe UI Variable', 'Segoe UI', 'Noto Sans', 'Ubuntu', 'Cantarell', 'Helvetica Neue', sans-serif"

_QSS = Template(
    """
* { font-family: $font; }
QWidget { color: $text; font-size: 13px; }
QLabel { background: transparent; }
QMainWindow, QDialog, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget { background: $bg; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 4px 6px; }

/* ---- sidebar ---- */
QWidget#sidebar { background: $nav_bg; border-right: 1px solid $border; }
QLabel#brand { font-size: 17px; font-weight: 700; padding: 0; }
QLabel#brandSub { color: $muted; font-size: 11px; }
QListWidget#nav { background: transparent; border: none; outline: none; }
QListWidget#nav::item { padding: 9px 12px; margin: 1px 8px; border-radius: 8px; color: $text; }
QListWidget#nav::item:hover { background: $surface2; }
QListWidget#nav::item:selected { background: $nav_sel; color: $accent; font-weight: 600; }
QLabel#sideFoot { color: $muted; font-size: 11px; }

/* ---- typography ---- */
QLabel[role="h1"] { font-size: 26px; font-weight: 700; letter-spacing: -0.5px; }
QLabel[role="h2"] { font-size: 15px; font-weight: 600; }
QLabel[role="title"] { font-size: 15px; font-weight: 600; }
QLabel[role="detailTitle"] { font-size: 20px; font-weight: 700; letter-spacing: -0.3px; }
QLabel[role="muted"] { color: $muted; }
QLabel[role="small"] { color: $muted; font-size: 12px; }
QLabel[role="stat"] { font-size: 30px; font-weight: 700; }
QLabel[role="section"] { color: $muted; font-size: 11px; font-weight: 700; letter-spacing: 1px; }

/* ---- buttons ---- */
QPushButton { background: $surface; border: 1px solid $border; border-radius: 6px; padding: 7px 14px; }
QPushButton:hover { background: $surface2; }
QPushButton:pressed { background: $sel; }
QPushButton:disabled { color: $disabled; background: $bg; }
QPushButton:focus { border: 2px solid $accent; padding: 6px 13px; }
QPushButton[primary="true"] { background: $accent; color: $accent_text; border: 1px solid $accent; font-weight: 600; }
QPushButton[primary="true"]:focus { padding: 6px 13px; }
QPushButton[primary="true"]:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton[primary="true"]:disabled { background: $surface2; color: $disabled; border-color: $border; }
QPushButton[danger="true"] { color: $bad; }
QPushButton[flat="true"] { border: none; background: transparent; color: $accent; padding: 4px 6px; }
QPushButton[flat="true"]:hover { text-decoration: underline; }

/* ---- inputs ---- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: $surface; border: 1px solid $border; border-radius: 6px; padding: 6px 8px;
    selection-background-color: $sel; selection-color: $text; }
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 2px solid $accent; padding: 5px 7px; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { width: 0; border: none; }
QComboBox { padding-right: 26px; min-height: 18px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: url($chevron); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border; selection-background-color: $sel; selection-color: $text; outline: none; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $border; border-radius: 4px; background: $surface; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url($check); }

/* ---- views ---- */
QTextBrowser { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 10px; selection-background-color: $sel; }
QListWidget { background: $surface; border: 1px solid $border; border-radius: 8px; outline: none; padding: 3px; }
QListWidget::item { padding: 6px 8px; border-radius: 6px; }
QListWidget::item:selected { background: $sel; color: $text; }
QListWidget::item:hover { background: $surface2; }
QTableWidget { background: $surface; alternate-background-color: $surface2; border: 1px solid $border; border-radius: 8px;
    gridline-color: transparent; selection-background-color: $sel; selection-color: $text; outline: none; }
QTableWidget::item { padding: 5px 8px; border: none; }
QHeaderView { background: transparent; }
QHeaderView::section { background: $surface; color: $muted; border: none; border-bottom: 1px solid $border;
    padding: 7px 8px; font-weight: 600; font-size: 12px; }
QTableCornerButton::section { background: $surface; border: none; }

/* ---- misc ---- */
QProgressBar { background: $surface2; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QStatusBar { background: $nav_bg; border-top: 1px solid $border; color: $muted; }
QStatusBar::item { border: none; }
QSplitter::handle { background: transparent; }
QScrollBar:vertical { background: transparent; width: 11px; margin: 0; }
QScrollBar::handle:vertical { background: $border; border-radius: 5px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 0; }
QScrollBar::handle:horizontal { background: $border; border-radius: 5px; min-width: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QMenu { background: $surface; border: 1px solid $border; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 5px; }
QMenu::item:selected { background: $sel; }

QFrame[role="tile"] { background: $surface; border: 1px solid $border; border-radius: 10px; }
QFrame[role="rule"] { background: $border; max-height: 1px; min-height: 1px; border: none; }
QFrame#dropZone { background: $surface; border: 2px dashed $border; border-radius: 12px; }
QFrame#dropZone[hover="true"] { border-color: $accent; background: $sel; }
QFrame[role="banner"] { background: $warn_bg; border: 1px solid $warn; border-radius: 8px; }
QFrame[role="info"] { background: $surface2; border: 1px solid $border; border-radius: 8px; }
QLabel[chip="good"] { background: $good_bg; color: $good; border-radius: 10px; padding: 3px 10px; font-size: 12px; font-weight: 600; }
QLabel[chip="bad"] { background: $bad_bg; color: $bad; border-radius: 10px; padding: 3px 10px; font-size: 12px; font-weight: 600; }
QLabel[chip="warn"] { background: $warn_bg; color: $warn; border-radius: 10px; padding: 3px 10px; font-size: 12px; font-weight: 600; }
/* ---- find jobs ---- */
QFrame[role="jobRow"] { background: $surface; border: 1px solid $border; border-radius: 10px; }
QFrame[role="jobRow"]:hover { background: $surface2; }
QFrame[role="jobRow"][selected="true"] { background: $sel; border: 2px solid $accent; }
QLabel[badge="good"] { background: $good_bg; color: $good; border-radius: 6px; font-weight: 700; font-size: 15px; padding: 4px 0; }
QLabel[badge="warn"] { background: $warn_bg; color: $warn; border-radius: 6px; font-weight: 700; font-size: 15px; padding: 4px 0; }
QLabel[badge="bad"] { background: $bad_bg; color: $bad; border-radius: 6px; font-weight: 700; font-size: 15px; padding: 4px 0; }
QLabel[badge="none"] { background: $surface2; color: $muted; border-radius: 6px; font-weight: 700; font-size: 15px; padding: 4px 0; }
QLabel[chip="accent"] { background: $accent; color: $accent_text; border-radius: 10px; padding: 3px 10px; font-size: 12px; font-weight: 600; }
QPushButton[seg] { border-radius: 0; margin: 0 0 0 -1px; padding: 7px 14px; border: 1px solid $border; }
QPushButton[seg]:checked { background: $accent; color: $accent_text; border-color: $accent; font-weight: 600; }
QPushButton[seg="left"] { border-top-left-radius: 6px; border-bottom-left-radius: 6px; margin-left: 0; }
QPushButton[seg="right"] { border-top-right-radius: 6px; border-bottom-right-radius: 6px; }
QCheckBox::indicator:hover { border-color: $accent; }
QLabel[chip="neutral"] { background: $surface2; color: $text; border-radius: 10px; padding: 3px 10px; font-size: 12px; }
"""
)


def build_qss(theme: str, chevron: Path, check: Path) -> str:
    p = PALETTES[theme]
    return _QSS.substitute(
        font=FONT_STACK,
        chevron=chevron.as_posix(),
        check=check.as_posix(),
        **p,
    )


def score_color(score: float | None, colors: dict[str, str]) -> str:
    if score is None:
        return colors["muted"]
    if score >= 75:
        return colors["good"]
    if score >= 50:
        return colors["warn"]
    return colors["bad"]
