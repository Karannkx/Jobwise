"""Common page scaffolding."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QVBoxLayout, QWidget

from ..context import AppContext
from ..widgets import label


class Page(QWidget):
    title = ""
    subtitle = ""

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.setObjectName("page")
        self.ctx = ctx
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(28, 24, 28, 20)
        self.root.setSpacing(14)
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(label(self.title, "h1"))
        if self.subtitle:
            head.addWidget(label(self.subtitle, "muted", wrap=True))
        self.root.addLayout(head)

    def refresh(self) -> None:  # called when the page is shown or data changes
        pass

    def apply_theme(self) -> None:
        pass


def fill_combo(combo: QComboBox, items: list[tuple[str, object]], placeholder: str, keep: bool = True) -> None:
    """Replace combo contents, keeping the current selection if still present."""
    current = combo.currentData() if keep else None
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(placeholder, None)
    for text, data in items:
        combo.addItem(text, data)
    idx = combo.findData(current) if current is not None else -1
    combo.setCurrentIndex(idx if idx >= 0 else 0)
    combo.blockSignals(False)


def row(*widgets, stretch_last: bool = False, spacing: int = 8) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    for i, w in enumerate(widgets):
        if w is None:
            lay.addStretch(1)
        else:
            lay.addWidget(w, 1 if (stretch_last and i == len(widgets) - 1) else 0)
    return lay
