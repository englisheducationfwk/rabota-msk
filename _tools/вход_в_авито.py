# -*- coding: utf-8 -*-
"""🔑 Один раз войти в Авито живым браузером — и профиль сохранится.

Первый визит с этого IP Авито встречает проверкой («Доступ ограничен» +
капча). Её проходит человек — как обычный посетитель: нажимает
«Продолжить», ставит галочку / собирает пазл. После этого окно само
закроется, а браузерный профиль ляжет в data/session/profile —
дальше проект ходит в Авито молча, от лица того же «браузера».

Весь трафик идёт через локальный мостик (bind к Wi-Fi) — то есть напрямую,
с российского IP, мимо туннеля Happ.

Запуск:  python _tools/вход_в_авито.py
Выход:   ❌ при закрытии окна до успеха; ✅ при сохранении профиля.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collector.netguard import wifi_ip  # noqa: E402

PROFILE = ROOT / "data" / "session" / "profile"
BRIDGE_PORT = 8790
URL = "https://www.avito.ru/moskva/rabota?q=%D0%B3%D0%BE%D1%80%D0%BD%D0%B8%D1%87%D0%BD%D0%B0%D1%8F&s=104"
WAIT_MIN = 720  # окно ждёт хоть весь день: закрывается само только на успехе


def bridge_alive() -> bool:
    """🌉 Слушает ли кто-то порт мостика."""
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", BRIDGE_PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def start_bridge() -> subprocess.Popen | None:
    """🚀 Поднять мостик отдельным процессом (если ещё не поднят)."""
    if bridge_alive():
        print(f"🌉 Мостик уже работает на порту {BRIDGE_PORT}")
        return None
    print(f"🌉 Поднимаю мостик (РУ-IP: {wifi_ip()})…")
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "_tools" / "proxy_bridge.py"),
         str(BRIDGE_PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(20):
        time.sleep(0.5)
        if bridge_alive():
            return proc
    print("❌ Мостик не поднялся")
    return proc


def main() -> int:
    from playwright.sync_api import sync_playwright

    PROFILE.mkdir(parents=True, exist_ok=True)
    start_bridge()

    print("🌐 Открываю живой браузер. Если Авито попросит проверку —")
    print("   нажмите «Продолжить» и пройдите её, как обычный посетитель.")
    print("   Окно само закроется, когда вход получится. Жду до "
          f"{WAIT_MIN} минут…")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE),
            headless=False,
            viewport={"width": 1100, "height": 760},
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            proxy={"server": f"http://127.0.0.1:{BRIDGE_PORT}"},
            args=["--disable-blink-features=AutomationControlled",
                  "--no-first-run", "--lang=ru-RU"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ Не открылась страница: {type(exc).__name__} {exc}")

        deadline = time.time() + WAIT_MIN * 60
        ok = False
        while time.time() < deadline:
            try:
                if page.is_closed():
                    print("❌ Окно закрыто до успеха — попробуйте ещё раз.")
                    break
                title = page.title()
                items = page.evaluate(
                    "document.querySelectorAll('[data-marker=\"item\"]').length")
                if "Доступ ограничен" not in title and items > 0:
                    ok = True
                    break
                # пока капча — мягко намекаем в заголовке вкладки
                if "Доступ ограничен" in title:
                    page.evaluate(
                        "document.title = '🔑 ПРОЙДИТЕ ПРОВЕРКУ — и этот "
                        "браузер запомнит вход';")
            except Exception:
                break
            time.sleep(3)

        if ok:
            print("✅ Вход получился! Вакансий на странице:",
                  page.evaluate(
                      "document.querySelectorAll('[data-marker=\"item\"]')"
                      ".length"))
            # даём браузеру дописать куки в профиль
            time.sleep(2)
        else:
            print("❌ Вход не завершён (тымаут или окно закрыто). "
                  "Запустите снова, когда сможете пройти проверку.")
        try:
            ctx.close()
        except Exception:
            pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
