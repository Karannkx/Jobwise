"""Shared state handed to every page."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QMessageBox, QVBoxLayout, QWidget

from ..errors import AIError, AINotConfiguredError, AppError
from ..services import Core
from . import theme
from .tasks import Task

log = logging.getLogger(__name__)

DISCLOSURE = (
    "To analyse resumes and job descriptions, this application sends text to Google's Gemini API, an "
    "external AI service.\n\n"
    "• Resume parsing sends the full text of the resume (including name and contact details).\n"
    "• Matching, skill-gap and role suggestions send an anonymised summary (no name, contact details, "
    "dates, schools or location).\n"
    "• Results are stored on this computer only; you can delete any candidate's data at any time.\n\n"
    "Only import documents you are allowed to process, and follow your organisation's privacy rules "
    "and applicable law. AI results are decision support, not hiring decisions."
)


class AppContext:
    def __init__(self, core: Core, window: QWidget):
        self.core = core
        self.window = window
        self._tasks: set[Task] = set()
        self._status: Callable[[str], None] = lambda _m: None
        self._on_data_changed: list[Callable[[], None]] = []

    # -- theme --------------------------------------------------------------
    @property
    def colors(self) -> dict[str, str]:
        return theme.PALETTES[self.core.settings.settings.theme]

    # -- status / change notification ------------------------------------------
    def set_status_sink(self, fn: Callable[[str], None]) -> None:
        self._status = fn

    def status(self, message: str) -> None:
        self._status(message)

    def on_data_changed(self, fn: Callable[[], None]) -> None:
        self._on_data_changed.append(fn)

    def data_changed(self) -> None:
        for fn in list(self._on_data_changed):
            try:
                fn()
            except Exception:
                log.exception("page refresh failed")

    # -- errors ---------------------------------------------------------------
    def show_error(self, exc: BaseException, title: str = "Something went wrong") -> None:
        if isinstance(exc, AppError):
            text = exc.user_message
        else:
            log.error("unexpected error", exc_info=(type(exc), exc, exc.__traceback__))
            text = "An unexpected error occurred. The details were written to the application log."
        box = QMessageBox(self.window)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(title)
        box.setText(text)
        if isinstance(exc, AINotConfiguredError):
            box.setInformativeText("Open Settings to add your Gemini API key.")
        box.exec()

    def info(self, title: str, text: str) -> None:
        QMessageBox.information(self.window, title, text)

    def confirm(self, title: str, text: str, danger: bool = False) -> bool:
        box = QMessageBox(self.window)
        box.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        return box.exec() == QMessageBox.Yes

    # -- AI disclosure ---------------------------------------------------------
    def ensure_ai_ready(self) -> bool:
        """Checks the API key exists and the user has acknowledged the data-transfer disclosure."""
        if not self.core.ai.is_configured():
            self.show_error(
                AINotConfiguredError(
                    "No Gemini API key is configured. Add one in Settings or set the GEMINI_API_KEY "
                    "environment variable."
                )
            )
            return False
        if self.core.settings.settings.disclosure_accepted:
            return True
        dlg = QDialog(self.window)
        dlg.setWindowTitle("Data sent to an external AI service")
        dlg.setMinimumWidth(520)
        lay = QVBoxLayout(dlg)
        text = QLabel(DISCLOSURE)
        text.setWordWrap(True)
        lay.addWidget(text)
        remember = QCheckBox("I understand. Don't show this again.")
        remember.setChecked(True)
        lay.addWidget(remember)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Continue")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        if dlg.exec() != QDialog.Accepted:
            return False
        if remember.isChecked():
            self.core.settings.update(disclosure_accepted=True)
        return True

    # -- background tasks ----------------------------------------------------------
    def run(
        self,
        fn: Callable[..., Any],
        on_done: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[BaseException], None]] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        busy: Optional[Callable[[bool], None]] = None,
    ) -> None:
        if busy:
            busy(True)

        def done(result):
            if busy:
                busy(False)
            if on_done:
                on_done(result)

        def failed(exc: BaseException):
            if busy:
                busy(False)
            if on_error:
                on_error(exc)
            else:
                self.show_error(exc)

        task = Task(fn, done, failed, on_progress, parent=self.window)
        self._tasks.add(task)
        task.finished.connect(lambda t=task: self._tasks.discard(t))
        task.start()

    @staticmethod
    def is_ai_error(exc: BaseException) -> bool:
        return isinstance(exc, AIError)
