"""Opening BabySitter again brings the window you already have to the front."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    asked_to_raise = Signal()

    def __init__(self, key: str = "BabySitter.single") -> None:
        super().__init__()
        self.key = key
        self.primary = False
        self.lock_failed = False
        self._server = QLocalServer(self)
        probe = QLocalSocket(self)
        probe.connectToServer(key)
        if probe.waitForConnected(250):
            probe.write(b"raise")
            probe.flush()
            probe.waitForBytesWritten(250)
            probe.disconnectFromServer()
            self.primary = False
            return
        QLocalServer.removeServer(key)
        self.primary = self._server.listen(key)
        if not self.primary:
            # Don't lock the user out if a stale name cannot be cleared.
            self.lock_failed = True
            self.primary = True
            return
        self._server.newConnection.connect(self._on_connection)

    def _on_connection(self) -> None:
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        socket.waitForReadyRead(250)
        data = bytes(socket.readAll())
        socket.disconnectFromServer()
        if b"raise" in data:
            self.asked_to_raise.emit()

    def release(self) -> None:
        """Stop holding the single-instance name so a restarted copy can open."""
        try:
            if self._server.isListening():
                self._server.close()
            QLocalServer.removeServer(self.key)
        except Exception:
            pass
