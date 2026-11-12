"""Per-user local IPC with a lock guarding stale endpoint cleanup."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QLockFile, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .security import event_id


class SingleInstance(QObject):
    activated = Signal(str)

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir).resolve()
        self.name = "GlobalPulse-" + hashlib.sha256(str(self.data_dir).encode()).hexdigest()[:24]
        self.lock = QLockFile(str(self.data_dir / "instance.lock"))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._connection)
        self.owner = False
        self._sockets = set()
        self.inbox = self.data_dir / "activation"
        self.inbox.mkdir(mode=0o700, exist_ok=True)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._mailbox)

    def acquire(self, target=""):
        if target:
            event_id(target)
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if socket.waitForConnected(700):
            payload = json.dumps({"event_id": target}).encode() + b"\n"
            written = socket.write(payload)
            delivered = written == len(payload) and (socket.bytesToWrite() == 0 or socket.waitForBytesWritten(700))
            socket.disconnectFromServer()
            if delivered:
                return False
        if not self.lock.tryLock(0):
            if self.lock.error() != QLockFile.LockError.LockFailedError:
                raise RuntimeError("Unable to establish the single-instance lock in this application data directory")
            # A file mailbox also works on desktops where local socket IPC is
            # unavailable. It carries only a validated event ID in the user's
            # private application directory, not executable commands.
            if len(list(self.inbox.glob("*.json"))) >= 32:
                raise RuntimeError("The running instance has too many pending activation requests")
            name = uuid.uuid4().hex
            temporary = self.inbox / (name + ".tmp")
            path = self.inbox / (name + ".json")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as out:
                    json.dump({"event_id": target}, out)
                    out.flush()
                    os.fsync(out.fileno())
                # The owner watches only .json files, so it cannot consume a
                # partially written request during a timer tick.
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            return False
        # Only the lock owner may remove a stale IPC socket.
        QLocalServer.removeServer(self.name)
        self.server.listen(self.name)
        self.owner = True
        self.timer.start()
        return True

    def _mailbox(self):
        for path in list(self.inbox.glob("*.json"))[:32]:
            try:
                if path.is_symlink() or path.stat().st_size > 2048 or time.time() - path.stat().st_mtime > 60:
                    path.unlink(missing_ok=True)
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                target = data.get("event_id", "")
                if target:
                    target = event_id(target)
                path.unlink()
                self.activated.emit(target)
            except (OSError, ValueError, TypeError, AttributeError):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _connection(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if len(self._sockets) >= 32:
                socket.abort()
                socket.deleteLater()
                continue
            self._sockets.add(socket)
            QTimer.singleShot(5000, lambda s=socket: s.abort() if s in self._sockets else None)
            socket.setProperty("buffer", b"")
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(lambda s=socket: self._discard(s))
            if socket.bytesAvailable():
                self._read(socket)

    def _discard(self, socket):
        self._sockets.discard(socket)
        socket.deleteLater()

    def _read(self, socket):
        data = bytes(socket.property("buffer") or b"") + bytes(socket.readAll())
        if len(data) > 2048:
            socket.abort()
            return
        socket.setProperty("buffer", data)
        if b"\n" not in data:
            return
        try:
            message = json.loads(data.split(b"\n", 1)[0])
            target = message.get("event_id", "")
            if target:
                target = event_id(target)
            self.activated.emit(target)
        except (ValueError, TypeError, AttributeError):
            pass
        socket.disconnectFromServer()

    def close(self):
        for socket in list(self._sockets):
            socket.abort()
        if self.owner:
            self.timer.stop()
            self.server.close()
            self.lock.unlock()
            self.owner = False

