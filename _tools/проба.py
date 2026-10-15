# -*- coding: utf-8 -*-
"""🧪 Проба: проходит ли Авито прямо сейчас (быстро, без записи в базу).

Открывает поиск живым браузером через профиль и мостик и говорит, что
видно: карточки, заслон или пусто. Ждёт до 90 секунд — заслон иногда
сам отпускает, если браузер ведёт себя «как человек».

Запуск:  python _tools/проба.py [--headless]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collector import store  # noqa: E402
from collector.netguard import ensure_bridge, make_session, check_ru  # noqa: E402

URL = ("https://www.avito.ru/moskva/rabota?q=%D0%B3%D0%BE%D1%80%D0%BD%D0%B8"
       "%D1%87%D0%BD%D0%B0%D1%8F&s=104")


def main() -> int:
    headless = "--headless" in sys.argv
    session = make_session()
    ok, msg = check_ru(session)
    print(("🛡️ " if ok else "⛔ ") + msg)
    ensure_bridge()

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(store.PROFILE_DIR), headless=headless,
            viewport={"width": 1280, "height": 900}, locale="ru-RU",
            timezone_id="Europe/Moscow",
            proxy={"server": "http://127.0.0.1:8790"},
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-background-timer-throttling",
                  "--disable-backgrounding-occluded-windows",
                  "--disable-renderer-backgrounding",
                  "--no-first-run"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if not headless:
            try:
                cdp = ctx.new_cdp_session(page)
                win = cdp.send("Browser.getWindowForTarget")
                cdp.send("Browser.setWindowBounds",
                         {"windowId": win["windowId"],
                          "bounds": {"windowState": "minimized"}})
            except Exception:
                pass
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:  # noqa: BLE001
            print("⚠️ переход:", type(exc).__name__, str(exc)[:120])
        deadline = time.time() + 90
        last = ""
        while time.time() < deadline:
            title = page.title()
            items = page.evaluate(
                "document.querySelectorAll('[data-marker=\"item\"]').length")
            state = f"{title!r}, карточек: {items}"
            if state != last:
                print("  ", state)
                last = state
            if "Доступ ограничен" not in title and items > 0:
                print("✅ Авито пускает!")
                html = page.content()
                (ROOT / "_research" / "live_search.html").write_text(
                    html, encoding="utf-8")
                print("   HTML сохранён в _research/live_search.html")
                ctx.close()
                return 0
            if "Доступ ограничен" in title and items == 0:
                # пробуем нажать «Продолжить» (показ капчи), ждём
                try:
                    btn = page.query_selector(
                        "form.js-firewall-form button[name=submit]")
                    if btn and btn.is_visible():
                        btn.click()
                except Exception:
                    pass
            time.sleep(4)
        print("⛔ Заслон не отпустил за 90 секунд")
        ctx.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
