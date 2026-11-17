"""Test fixtures for secure-connection (TLS) faults.

* make_cert()     – a throwaway self-signed certificate for "weather.test"
                    (openssl command line; tests skip if it's missing)
* TLSFakeServer   – the normal fake Open-Meteo server, but over HTTPS
* SilentServer    – accepts TCP connections and then never sends a byte:
                    exactly what a stalled TLS handshake looks like to the
                    client ("_ssl.c: The handshake operation timed out")
"""

from __future__ import annotations

import shutil
import socket
import ssl
import subprocess
import threading
from pathlib import Path

from fake_server import FakeServer

HOST = "weather.test"


def openssl_available() -> bool:
    return shutil.which("openssl") is not None


def make_cert(directory: Path) -> tuple[Path, Path]:
    cert, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                    "-subj", f"/CN={HOST}", "-addext", f"subjectAltName=DNS:{HOST}",
                    "-keyout", str(key), "-out", str(cert)],
                   check=True, capture_output=True)
    return cert, key


class TLSFakeServer(FakeServer):
    def __init__(self, cert: Path, key: Path):
        super().__init__()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert), str(key))
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)

    @property
    def forecast_url(self):
        return f"https://{HOST}:{self.port}/v1/forecast"

    @property
    def geocode_url(self):
        return f"https://{HOST}:{self.port}/v1/search"

    @property
    def metno_url(self):
        from fake_server import METNO_PATH
        return f"https://{HOST}:{self.port}{METNO_PATH}"


class SilentServer:
    """Accepts connections, reads nothing useful, never replies."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self.accepted: list[socket.socket] = []
        self._stop = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        self.sock.settimeout(0.2)
        while not self._stop:
            try:
                c, _ = self.sock.accept()
                self.accepted.append(c)
            except (socket.timeout, OSError):
                continue

    @property
    def connections(self) -> int:
        return len(self.accepted)

    def close(self):
        self._stop = True
        self.thread.join(2)
        for c in self.accepted:
            c.close()
        self.sock.close()


def client_context(cert: Path) -> ssl.SSLContext:
    """Client context trusting only the throwaway certificate (verification stays on)."""
    ctx = ssl.create_default_context(cafile=str(cert))
    return ctx
