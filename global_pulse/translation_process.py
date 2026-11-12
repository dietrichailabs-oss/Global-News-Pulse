"""One owned bounded translation process, private temporary IPC and finite queue."""
from __future__ import annotations
from collections import deque
import json
from pathlib import Path
import shutil
import sys
import tempfile
from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class TranslationProcess(QObject):
    completed = Signal(str, str, str, str)  # report ID, language, text, error
    progress = Signal(str, int, int)

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir).resolve()
        self.queue = deque()
        self.process = None
        self.current = None
        self.work_dir = None
        self._closed = False
        self._failure = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timeout)
        self.inference_timeout_ms = 120000
        self.download_timeout_ms = 600000
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(250)
        self._progress_timer.timeout.connect(self._read_progress)

    def command(self):
        if getattr(sys, "frozen", False):
            return sys.executable, ["--translation-worker"]
        return sys.executable, ["-m", "global_pulse.translation_worker"]

    def submit(self, rid, language, text, install):
        if self._closed or len(self.queue) + bool(self.current) >= 8:
            return False
        if len(text) > 4000 or type(install) is not bool:
            raise ValueError("Invalid translation request")
        self.queue.append((rid, language, text, install))
        self._next()
        return True

    def _next(self):
        if self._closed or self.current or not self.queue:
            return
        self.current = self.queue.popleft()
        self._failure = ""
        try:
            jobs = self.data_dir / "translation-jobs"
            if jobs.is_symlink() or jobs.resolve() != jobs:
                raise ValueError("Translation work root must not redirect")
            jobs.mkdir(exist_ok=True, mode=0o700)
            self.work_dir = Path(tempfile.mkdtemp(prefix="job-", dir=jobs))
            _, language, text, install = self.current
            request = {"data_dir": str(self.data_dir), "work_dir": str(self.work_dir),
                       "language": language, "text": text, "install": install}
            encoded = json.dumps(request, ensure_ascii=False).encode("utf-8")
            if len(encoded) > 32768:
                raise ValueError("Translation request exceeds limit")
            (self.work_dir / "request.json").write_bytes(encoded)
        except (ValueError, OSError):
            self._complete("", "Translation workspace unavailable")
            return
        process = QProcess(self)
        self.process = process
        process.setWorkingDirectory(str(Path(__file__).resolve().parent.parent))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        # No source text or worker diagnostic output is logged by the parent.
        process.readyReadStandardOutput.connect(lambda: process.readAllStandardOutput())
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._error)
        program, arguments = self.command()
        self._timer.start(self.download_timeout_ms if self.current[3] else self.inference_timeout_ms)
        process.start(program, arguments + ["--job", str(self.work_dir)])
        self._progress_timer.start()

    def _read_progress(self):
        if not self.current or not self.work_dir:
            return
        path = self.work_dir / "progress.json"
        try:
            if path.is_symlink():
                return
            with path.open("rb") as source:
                raw = source.read(1025)
            if len(raw) > 1024:
                return
            value = json.loads(raw)
            received, total = value["received"], value["total"]
            if type(received) is int and type(total) is int and 0 <= received <= total <= 1_000_000_000:
                self.progress.emit(self.current[0], received, total)
        except (OSError, ValueError, KeyError, TypeError):
            return

    def cancel(self, rid):
        for item in list(self.queue):
            if item[0] == rid:
                self.queue.remove(item)
                self.completed.emit(item[0], item[1], "", "Download cancelled")
                return True
        if self.current and self.current[0] == rid and self.process:
            self._failure = "Download cancelled"
            self.process.kill()
            return True
        return False

    def _timeout(self):
        if self.process and self.current:
            self._failure = "Translation time limit exceeded"
            self.process.kill()

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.current:
            self._complete("", "Translation worker could not start")

    def _finished(self, exit_code, exit_status):
        self._timer.stop()
        if not self.current or self._closed:
            return
        text, error = "", self._failure
        if not error:
            try:
                response = self.work_dir / "response.json"
                if response.is_symlink() or not response.is_file():
                    raise ValueError("Invalid worker result path")
                with response.open("rb") as source:
                    raw = source.read(65537)
                if len(raw) > 65536:
                    raise ValueError("Worker result exceeds limit")
                result = json.loads(raw)
                if not isinstance(result, dict) or set(result) != {"text", "error"} or not all(isinstance(x, str) for x in result.values()):
                    raise ValueError("Invalid worker result")
                text, error = result["text"], result["error"]
                if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
                    error = error or "Translation worker exited unexpectedly"
            except (OSError, ValueError, TypeError):
                error = "Invalid translation worker result"
        self._complete(text if not error else "", error)

    def _cleanup(self):
        if self.work_dir:
            # Only this random, parent-created child directory is removed.
            if self.work_dir.is_symlink() or self.work_dir.resolve() != self.work_dir:
                raise RuntimeError("Translation workspace cleanup refused a redirected path")
            try:
                if self.work_dir.exists():
                    shutil.rmtree(self.work_dir)
            except OSError as exc:
                raise RuntimeError("Translation workspace cleanup failed") from exc
        self.work_dir = None

    def _complete(self, text, error):
        self._timer.stop()
        self._progress_timer.stop()
        rid, language, _, _ = self.current
        self.current = None
        process, self.process = self.process, None
        if process:
            process.deleteLater()
        try:
            self._cleanup()
        except RuntimeError:
            text, error = "", "Translation workspace cleanup failed"
            # Stop further work instead of accumulating source-bearing job files.
            self._closed = True
            self.queue.clear()
            self.completed.emit(rid, language, text, error)
            return
        if not self._closed:
            self.completed.emit(rid, language, text, error)
            QTimer.singleShot(0, self._next)

    def close(self):
        self._progress_timer.stop()
        self._closed = True
        self._timer.stop()
        self.queue.clear()
        process = self.process
        if process and process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
            if not process.waitForFinished(2500):
                raise RuntimeError("Translation worker termination was not confirmed")
        self.current = None
        self.process = None
        if process:
            process.deleteLater()
        self._cleanup()
