"""The window that records your voice for the natural-voice helper.

Read the passage, listen back, keep it or try again. Recording and the
listen-back run off the window's thread, so the window never freezes. The
take is only written to disk when you press Keep it (`ownvoice.save`).
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from babysitter import ownvoice
from babysitter.ui.dialogs import _box


class _RecordJob(QThread):
    finished_take = Signal(object, int)
    failed = Signal(str)

    def __init__(self, device, stop: threading.Event) -> None:
        super().__init__()
        self._device = device
        self._stop = stop

    def run(self) -> None:
        try:
            samples, rate = ownvoice.record(ownvoice.RECORD_SECONDS, self._device, self._stop)
        except Exception as exc:  # noqa: BLE001 - a headset switched off, a busy device
            self.failed.emit(f"The microphone could not record ({type(exc).__name__}). Check it in Settings, then try again.")
            return
        self.finished_take.emit(samples, rate)


class _PlayJob(QThread):
    def __init__(self, samples, rate: int) -> None:
        super().__init__()
        self._samples = samples
        self._rate = rate

    def run(self) -> None:
        try:
            import sounddevice as sd

            sd.play(self._samples, self._rate)
            sd.wait()
        except Exception:  # noqa: BLE001 - listening back is a nicety
            pass


class RecordVoiceDialog:
    """Owns the dialog. `run()` returns the sentence to show afterwards, or ""."""

    def __init__(self, parent, device) -> None:
        self.result = ""
        self._device = device
        self._take = None
        self._rate = 0
        self._stop = threading.Event()
        self._jobs: list[QThread] = []
        self._left = 0

        dialog = _box(parent, "Record your voice")
        dialog.setMinimumWidth(520)
        self.dialog = dialog
        layout = QVBoxLayout(dialog)
        how = QLabel(
            "Find a quiet spot. Press Start, then read this out loud at your normal pace, "
            f"the way you would talk to a friend. It records for {ownvoice.RECORD_SECONDS} seconds."
        )
        how.setWordWrap(True)
        layout.addWidget(how)
        passage = QLabel(ownvoice.PASSAGE)
        passage.setWordWrap(True)
        passage.setObjectName("section")
        passage.setAccessibleName("Passage to read")
        layout.addWidget(passage)
        self.status = QLabel("Ready when you are.")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Recording status")
        layout.addWidget(self.status)

        row = QHBoxLayout()
        self.start = QPushButton("Start recording")
        self.start.setObjectName("primary")
        self.start.clicked.connect(self._start)
        self.finish = QPushButton("Stop early")
        self.finish.setEnabled(False)
        self.finish.clicked.connect(self._stop.set)
        self.listen = QPushButton("Listen back")
        self.listen.setEnabled(False)
        self.listen.clicked.connect(self._listen)
        self.keep = QPushButton("Keep it")
        self.keep.setEnabled(False)
        self.keep.clicked.connect(self._keep)
        close = QPushButton("Cancel")
        close.clicked.connect(dialog.reject)
        for button in (self.start, self.finish, self.listen, self.keep, close):
            row.addWidget(button)
        layout.addLayout(row)

        self._tick = QTimer(dialog)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._count)
        dialog.finished.connect(lambda _code: self._stop.set())

    def run(self) -> str:
        self.dialog.exec()
        self._stop.set()
        for job in self._jobs:
            job.wait(3000)
        return self.result

    def _start(self) -> None:
        self._stop.clear()
        self._take = None
        self.start.setEnabled(False)
        self.listen.setEnabled(False)
        self.keep.setEnabled(False)
        self.finish.setEnabled(True)
        self._left = ownvoice.RECORD_SECONDS
        self.status.setText(f"Recording… {self._left} seconds left. Read the passage now.")
        self._tick.start()
        job = _RecordJob(self._device, self._stop)
        job.finished_take.connect(self._got_take)
        job.failed.connect(self._failed)
        self._jobs.append(job)
        job.start()

    def _count(self) -> None:
        self._left = max(0, self._left - 1)
        if self._left:
            self.status.setText(f"Recording… {self._left} seconds left.")

    def _failed(self, why: str) -> None:
        self._tick.stop()
        self.finish.setEnabled(False)
        self.start.setEnabled(True)
        self.start.setText("Try again")
        self.status.setText(why)

    def _got_take(self, samples, rate: int) -> None:
        self._tick.stop()
        self.finish.setEnabled(False)
        self.start.setEnabled(True)
        self.start.setText("Try again")
        trimmed, problem = ownvoice.check_take(samples, rate)
        if problem:
            self.status.setText(problem)
            return
        self._take, self._rate = samples, rate
        self.listen.setEnabled(True)
        self.keep.setEnabled(True)
        self.status.setText(
            f"That sounds usable ({len(trimmed) / rate:.0f} seconds of speech). Listen back if you like, then press Keep it."
        )

    def _listen(self) -> None:
        if self._take is None:
            return
        trimmed, _problem = ownvoice.check_take(self._take, self._rate)
        job = _PlayJob(trimmed if trimmed is not None else self._take, self._rate)
        self._jobs.append(job)
        job.start()

    def _keep(self) -> None:
        if self._take is None:
            return
        try:
            self.result = ownvoice.save(self._take, self._rate)
        except (ownvoice.OwnVoiceError, OSError) as exc:
            self.status.setText(str(exc))
            return
        self.dialog.accept()
