"""Background workers: QRunnable wrappers that run services on a thread pool
(or a dedicated QThread for the long-running backfill loop) and report back
through Qt signals."""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThread, Signal

log = logging.getLogger("workers")


class JobSignals(QObject):
    progress = Signal(int, int, str)
    done = Signal(object)
    error = Signal(str)


class Job(QRunnable):
    """Run `fn(*args, **kwargs)` off the GUI thread. fn may accept a
    `progress` keyword that receives (cur, total, msg) tuples."""

    def __init__(self, fn: Callable, *args: Any, **kwargs: Any):
        super().__init__()
        self.signals = JobSignals()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.setAutoDelete(True)

    def run(self) -> None:  # noqa: A003
        try:
            progress_cb = None
            kwargs = dict(self._kwargs)
            if "_progress" in kwargs:
                progress_cb = kwargs.pop("_progress")
            result = self._fn(*self._args, **kwargs, progress=progress_cb)\
                if progress_cb else self._fn(*self._args, **kwargs)
            self.signals.done.emit(result)
        except Exception as exc:  # noqa: BLE001
            log.exception("job failed")
            self.signals.error.emit(f"{type(exc).__name__}: {exc}")


class StopFlag:
    def __init__(self) -> None:
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def is_set(self):
        return self._stopped

    def __bool__(self):
        return self._stopped

    def __call__(self) -> bool:
        return self._stopped


class BackfillThread(QThread):
    """Dedicated thread running the pending-problems backfill until stopped."""

    progress = Signal(int, int, str)
    finished_stats = Signal(object)
    log_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stop_flag = StopFlag()

    def request_stop(self) -> None:
        self.stop_flag.stop()

    def run(self) -> None:  # noqa: A003
        from .services import sync

        def cb(cur, total, msg):
            self.progress.emit(cur, total, msg)

        stats = sync.run_backfill(self.stop_flag, cb)
        self.finished_stats.emit(stats)


def pool() -> "QThreadPool":
    from PySide6.QtCore import QThreadPool
    return QThreadPool.globalInstance()