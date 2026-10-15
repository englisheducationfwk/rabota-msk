# -*- coding: utf-8 -*-
"""🌉 Локальный мостик-прокси: браузер ходит в Авито мимо Happ.

Chromium не умеет привязываться к сетевому интерфейсу, поэтому поднимаем
крошечный HTTP-прокси (CONNECT-туннель), который сам делает bind к IP
локального адаптера. Браузер запускается с --proxy-server=127.0.0.1:8790
и видит российский IP — как будто VPN выключен.

Запуск: python _tools/proxy_bridge.py [порт]
Слушает только 127.0.0.1 — снаружи недоступен.
"""

from __future__ import annotations

import selectors
import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.netguard import wifi_ip  # noqa: E402

HOST = "127.0.0.1"
PORT = 8790
BUFSIZE = 65536


def _connect_direct(host: str, port: int) -> socket.socket:
    """🔌 Соединение с внешним миром НАПРЯМУЮ (bind к Wi-Fi)."""
    ip = wifi_ip() or wifi_ip(refresh=True)
    last: Exception | None = None
    for family, _, _, _, addr in socket.getaddrinfo(
            host, port, type=socket.SOCK_STREAM):
        if family != socket.AF_INET:
            continue
        s = socket.socket(family, socket.SOCK_STREAM)
        s.settimeout(20)
        try:
            if ip:
                s.bind((ip, 0))
            s.connect(addr)
            s.settimeout(None)
            return s
        except OSError as exc:
            last = exc
            s.close()
    raise OSError(f"connect {host}:{port} failed: {last}")


def _pump(a: socket.socket, b: socket.socket) -> None:
    """↔️ Перекачка байт между двумя сокетами до закрытия любого."""
    sel = selectors.DefaultSelector()
    sel.register(a, selectors.EVENT_READ)
    sel.register(b, selectors.EVENT_READ)
    try:
        while True:
            for key, _ in sel.select(timeout=120):
                data = key.fileobj.recv(BUFSIZE)  # type: ignore[union-attr]
                if not data:
                    return
                other = b if key.fileobj is a else a
                other.sendall(data)
    except OSError:
        return
    finally:
        sel.close()
        for s in (a, b):
            try:
                s.close()
            except OSError:
                pass


def _read_head(conn: socket.socket) -> tuple[bytes, bytes]:
    """📥 Первая строка запроса + оставшиеся принятые байты."""
    data = b""
    while b"\r\n" not in data and len(data) < 65536:
        chunk = conn.recv(BUFSIZE)
        if not chunk:
            break
        data += chunk
    line, _, rest = data.partition(b"\r\n")
    return line, rest


def _handle(conn: socket.socket) -> None:
    try:
        line, rest = _read_head(conn)
        if not line:
            return
        parts = line.split()
        if len(parts) < 3:
            return
        method, target, _ = parts[0].decode(), parts[1].decode(), parts[2]

        if method.upper() == "CONNECT":
            host, _, port_s = target.partition(":")
            upstream = _connect_direct(host, int(port_s or 443))
            conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            _pump(conn, upstream)
            return

        # Обычный HTTP: цель — абсолютный URL
        if target.startswith("http://"):
            rest_url, _, path = target[8:].partition("/")
            host, _, port_s = rest_url.partition(":")
            upstream = _connect_direct(host, int(port_s or 80))
            new_line = (method + " /" + path + " " +
                        parts[2].decode()).encode()
            upstream.sendall(new_line + b"\r\n" + rest)
            _pump(conn, upstream)
            return
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def serve(port: int = PORT) -> None:
    """🚀 Поднять прокси (блокирующий цикл; остановка — Ctrl+C)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, port))
    srv.listen(64)
    print(f"Мостик слушает http://{HOST}:{port}  (bind -> {wifi_ip()})")
    while True:
        try:
            conn, _ = srv.accept()
        except OSError:
            break
        threading.Thread(target=_handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else PORT)
