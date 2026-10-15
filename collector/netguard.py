# -*- coding: utf-8 -*-
"""🛡️ Прямой РУ-канал: ходим в Авито мимо VPN-туннеля.

На этом ПК включён Happ — TUN-туннель, весь трафик уходит за границу.
Авито пускает только российские IP, поэтому весь сетевой код проекта
ходит НАПРЯМУЮ: привязывается к IP локального адаптера (bind к источнику).
Проверено 15.10.2026: с bind внешний адрес — 37.110.151.10, RU, Химки.

Плюс страж: перед сбором убеждаемся, что наружу выходим как RU; если
страна чужая — сбор останавливается с понятной подсказкой.
"""

from __future__ import annotations

import socket
import subprocess
import time

BRIDGE_PORT = 8790

_HINT = ("Похоже, весь трафик уходит через туннель (Happ). "
         "Проверьте, что Wi-Fi подключён, и нажмите «Включить» снова. "
         "Если не поможет — на время сбора выключите Happ.")

_cache: dict[str, str | None] = {"ip": None}


def _ps(cmd: str) -> str:
    """🖥️ Однострочник PowerShell → строка (пусто при ошибке)."""
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return done.stdout.strip()
    except Exception:
        return ""


def wifi_ip(refresh: bool = False) -> str | None:
    """📡 IPv4 адрес локального адаптера (по умолчанию Wi-Fi), или None.

    Адрес может меняться при переподключении — поэтому можно обновить.
    """
    if _cache["ip"] and not refresh:
        return _cache["ip"]
    for alias in ("Wi-Fi", "Ethernet", "WLAN"):
        out = _ps(f"(Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "
                  f"'{alias}' -ErrorAction SilentlyContinue).IPAddress")
        for line in out.splitlines():
            line = line.strip()
            if line and not line.startswith("169.254."):
                _cache["ip"] = line
                return line
    _cache["ip"] = None
    return None


def external_info(session) -> dict:
    """🌍 Каким адресом и из какой страны нас видит интернет.

    session — curl_cffi.Session; при ошибке вернёт {"error": ...}.
    """
    try:
        r = session.get("https://ipinfo.io/json", timeout=20)
        return r.json()
    except Exception as exc:  # noqa: BLE001 — любая сетевая беда = не РУ
        return {"error": f"{type(exc).__name__}: {exc}"}


def check_ru(session, attempts: int = 3) -> tuple[bool, str]:
    """✅ (ок, сообщение): выходим ли мы в интернет как Россия.

    До attempts попыток: разовый сетевой сбой или мигнувший туннель
    не должны останавливать сбор. Стоп — только если все попытки мимо.
    """
    info: dict = {}
    for _ in range(max(1, attempts)):
        info = external_info(session)
        if "error" not in info and \
                (info.get("country") or "").upper() == "RU":
            ip = info.get("ip") or "?"
            city = info.get("city") or ""
            return True, f"РУ-IP подтверждён: {ip} ({city})"
        time.sleep(2)
    if "error" in info:
        return False, f"Не удалось проверить IP: {info['error']}. {_HINT}"
    country = (info.get("country") or "?").upper()
    ip = info.get("ip") or "?"
    return False, (f"Интернет видит нас как {country} ({ip}). {_HINT}")


def make_session():
    """🔌 curl_cffi-сессия, ходящая НАПРЯМУЮ (bind к Wi-Fi) — мимо Happ.

    Impersonate=chrome даёт отпечаток настоящего Chrome (часть антибота
    отпадает сама). Если bind не удался — вернём обычную сессию: страж
    check_ru() потом честно скажет, что мы «не РУ».
    """
    from curl_cffi import requests as creq

    class DirectSession(creq.Session):
        def request(self, method, url, *args, **kwargs):
            ip = wifi_ip()
            if ip and "interface" not in kwargs:
                kwargs["interface"] = ip
            if "impersonate" not in kwargs:
                kwargs["impersonate"] = "chrome"
            return super().request(method, url, *args, **kwargs)

    return DirectSession()


def bridge_alive(port: int = BRIDGE_PORT) -> bool:
    """🌉 Слушает ли локальный мостик (через него ходит браузер)."""
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def ensure_bridge(port: int = BRIDGE_PORT):
    """🚀 Поднять мостик, если ещё не поднят (нужен для браузера)."""
    if bridge_alive(port):
        return None
    import sys
    from pathlib import Path
    bridge = Path(__file__).resolve().parent.parent / "_tools" / \
        "proxy_bridge.py"
    proc = subprocess.Popen(
        [sys.executable, str(bridge), str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(20):
        if bridge_alive(port):
            return proc
        import time as _t
        _t.sleep(0.5)
    return proc
