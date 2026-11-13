"""Background execution so the UI never blocks on documents, the database or the network."""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)
    progress = Signal(int, int, str)


class _Runnable(QRunnable):
    def __init__(self, fn: Callable[..., Any], signals: _Signals, wants_progress: bool):
        super().__init__()
        self._fn = fn
        self._signals = signals
        self._wants_progress = wants_progress

    def run(self) -> None:
        try:
            if self._wants_progress:
                result = self._fn(self._signals.progress.emit)
            else:
                result = self._fn()
        except BaseException as exc:  # noqa: BLE001 - everything is reported to the UI thread
            self._signals.failed.emit(exc)
        else:
            self._signals.done.emit(result)


class Task(QObject):
    """Lives in the GUI thread; callbacks always run there."""

    finished = Signal()

    def __init__(
        self,
        fn: Callable[..., Any],
        on_done: Optional[Callable[[Any], None]],
        on_error: Callable[[BaseException], None],
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._on_done, self._on_error, self._on_progress = on_done, on_error, on_progress
        self._signals = _Signals(self)
        self._signals.done.connect(self._handle_done)
        self._signals.failed.connect(self._handle_failed)
        self._signals.progress.connect(self._handle_progress)
        self._runnable = _Runnable(fn, self._signals, on_progress is not None)
        self._runnable.setAutoDelete(False)

    def start(self) -> None:
        QThreadPool.globalInstance().start(self._runnable)

    @Slot(object)
    def _handle_done(self, result: Any) -> None:
        try:
            if self._on_done:
                self._on_done(result)
        except BaseException as exc:  # noqa: BLE001
            self._on_error(exc)
        finally:
            self.finished.emit()

    @Slot(object)
    def _handle_failed(self, exc: BaseException) -> None:
        try:
            self._on_error(exc)
        finally:
            self.finished.emit()

    @Slot(int, int, str)
    def _handle_progress(self, cur: int, total: int, msg: str) -> None:
        if self._on_progress:
            self._on_progress(cur, total, msg)
