"""Bundled Inter font (OFL) so the UI looks the same on Windows and Linux."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)
_loaded = False


def load_fonts(font_dir: Path) -> bool:
    """Register bundled fonts with Qt and make Inter the application default. Returns True if loaded."""
    global _loaded
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    if _loaded:
        return True
    ok = 0
    for f in sorted(font_dir.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(f)) >= 0:
            ok += 1
        else:
            log.warning("could not load font %s", f.name)
    if ok and QApplication.instance():
        font = QFont("Inter")
        font.setPixelSize(13)
        font.setHintingPreference(QFont.PreferNoHinting)
        QApplication.instance().setFont(font)
    _loaded = ok > 0
    return _loaded
