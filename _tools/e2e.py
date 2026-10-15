# -*- coding: utf-8 -*-
"""🖥️ E2E: страница на локальном сервере + скриншоты.

Кладёт демо-данные (или реальный срез из data/vacancies.json, если он
есть), поднимает http на 8788 поверх docs/ и снимает скриншоты:
iPhone-вид (390x844) и широкий — плюс проверяет, что карточки рисуются.

Запуск:  python _tools/e2e.py [--demo]
Результат: _shots/*.png + краткий отчёт в консоль.
"""

from __future__ import annotations

import functools
import json
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "_shots"
DOCS = ROOT / "docs"
DATA = DOCS / "data" / "vacancies.json"


def demo_payload() -> dict:
    """🎭 Демо-вакансии: разные случаи, как в жизни (для проверки вида)."""
    now = int(time.time())
    items = [
        dict(id="1", title="Горничная в отель 5*, Тверская",
             url="https://www.avito.ru/demo/1", price="5 000 ₽ за смену",
             salary_month=105000, salary_unit="смена", employer="Отель Ритц",
             metro="м. Тверская", address="Москва, ул. Тверская",
             published=now - 600, published_text="сегодня в 17:02",
             description=(
                 "Уборка номеров, 15 номеров за смену. График 2/2, "
                 "смены с 9 до 21. Без оформления, оплата на руки в конце "
                 "смены. Питание и форма предоставляются."),
             score=92, reasons=["+20, Оплата 5 000 ₽ за смену — хорошо",
                                "+15, Без оформления / на руки",
                                "+15, Рейтинг работодателя 4.8 (23 отз.)",
                                "+10, Опубликовано только что"],
             unofficial=True, housing=False, first_seen=now - 500,
             rating={"score": 4.8, "reviews": 23}, employer_id="77",
             status="new", query="горничная"),
        dict(id="2", title="Домработница в частный дом, Барвиха",
             url="https://www.avito.ru/demo/2", price="90 000 ₽",
             salary_month=90000, salary_unit="месяц", employer="Семья",
             metro="", address="Московская обл., Барвиха",
             published=now - 3600 * 3, published_text="сегодня в 14:40",
             description=(
                 "Семья ищет домработницу. Уборка дома 300 м², глажка, "
                 "простая готовка. Пятидневка. Помощь по хозяйству. "
                 "Обязательно с опытом в частных домах."),
             score=78, reasons=["+10, Оплата 90 000 ₽",
                                "+8, Рейтинг работодателя 4.2 (7 отз.)"],
             unofficial=False, housing=True, first_seen=now - 3600,
             rating={"score": 4.2, "reviews": 7}, employer_id="88",
             status="new", query="домработница"),
        dict(id="3", title="Уборщица в бизнес-центр, смена 12 часов",
             url="https://www.avito.ru/demo/3", price="3 800 ₽ за смену",
             salary_month=79800, salary_unit="смена",
             employer="Клининговая компания",
             metro="м. Киевская", address="Москва, БЦ",
             published=now - 3600 * 26, published_text="вчера в 15:10",
             description=(
                 "Уборка офисных помещений по маршруту. Смена 12 часов, "
                 "график 1/1 или 2/2 на выбор. Ежедневная оплата на карту "
                 "или наличными."),
             score=71, reasons=["+15, Без оформления / на руки",
                                "+5, Свежая вакансия (сегодня)"],
             unofficial=True, housing=False, first_seen=now - 3600 * 25,
             rating={"score": 4.6, "reviews": 112}, employer_id="99",
             status="new", query="уборщица"),
        dict(id="4", title="Горничная (вахта, проживание)",
             url="https://www.avito.ru/demo/4", price="по договорённости",
             salary_month=0, salary_unit="", employer="",
             metro="м. Планерная", address="Москва",
             published=now - 3600 * 50, published_text="12 октября в 11:20",
             description=(
                 "Вахта 15/15 в загородном доме отдыха. Проживание в "
                 "хорошем общежитии, питание. Уборка номеров."),
             score=54, reasons=["-8, Зарплата не указана"],
             unofficial=False, housing=True, first_seen=now - 3600 * 49,
             rating={}, employer_id="", status="new", query="горничная вахта"),
    ]
    return {"updated": now, "new_since": now - 86400, "count": len(items),
            "items": items}


def main() -> int:
    use_demo = "--demo" in sys.argv or not DATA.exists()
    if use_demo:
        DATA.parent.mkdir(parents=True, exist_ok=True)
        DATA.write_text(json.dumps(demo_payload(), ensure_ascii=False),
                        encoding="utf-8")
        print("🎭 Демо-данные разложены")

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(DOCS))
    httpd = ThreadingHTTPServer(("127.0.0.1", 8788), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print("🌐 Локальный сервер: http://127.0.0.1:8788/")

    SHOTS.mkdir(exist_ok=True)
    from playwright.sync_api import sync_playwright
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # iPhone-вид
        page = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2, is_mobile=True, has_touch=True,
            user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like "
                        "Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
                        "Version/17.0 Mobile/15E148 Safari/604.1"),
        ).new_page()
        console_errors: list[str] = []
        page.on("pageerror", lambda e: console_errors.append(str(e)))
        page.goto("http://127.0.0.1:8788/index.html",
                  wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(800)
        cards = page.locator(".card").count()
        print(f"📱 Карточек на странице: {cards}")
        if cards == 0:
            errors.append("карточки не отрисовались")
        if console_errors:
            errors.append("ошибки JS: " + "; ".join(console_errors[:3]))
        page.screenshot(path=str(SHOTS / "page_iphone.png"))

        # прокрутка вниз — вторая карточка в кадре + кнопка «наверх»
        page.mouse.wheel(0, 700)
        page.wait_for_timeout(500)
        page.screenshot(path=str(SHOTS / "page_iphone_scroll.png"))
        to_top_visible = page.evaluate(
            "!document.getElementById('to-top').hidden")
        print(f"📱 Кнопка «наверх» показалась: {to_top_visible}")
        if not to_top_visible:
            errors.append("кнопка «наверх» не показалась при прокрутке")

        # фильтр «без оформления»
        page.click('[data-filter="unofficial"]')
        page.wait_for_timeout(400)
        cards2 = page.locator(".card").count()
        page.screenshot(path=str(SHOTS / "page_filter_unofficial.png"))
        print(f"📱 После фильтра «без оформления»: {cards2}")
        if cards2 == 0 or cards2 == cards:
            errors.append("фильтр «без оформления» ничего не изменил")
        page.click('[data-filter="unofficial"]')  # снять фильтр
        page.wait_for_timeout(300)

        # «Не подходит» — карточка исчезает сразу
        page.click('.card .hide-act')
        page.wait_for_timeout(400)
        cards3 = page.locator(".card").count()
        print(f"📱 После «Не подходит»: {cards3}")
        if cards3 >= cards:
            errors.append("«Не подходит» не убрал карточку")

        # «Заблокировать» — с подтверждением
        page.on("dialog", lambda d: d.accept())
        page.click('.card .block-act')
        page.wait_for_timeout(400)
        cards4 = page.locator(".card").count()
        unblock = page.locator("#unblock-chip").count()
        print(f"📱 После блокировки: {cards4} карточек, "
              f"чип «Разблокировать»: {unblock}")
        if unblock == 0:
            errors.append("нет чипа «Разблокировать» после блокировки")
        page.screenshot(path=str(SHOTS / "page_after_block.png"))
        if unblock:
            page.click("#unblock-chip")  # вернуть
            page.wait_for_timeout(300)

        # широкая версия
        wide = page.context.browser.new_context(
            viewport={"width": 1280, "height": 900}).new_page()
        wide.goto("http://127.0.0.1:8788/index.html",
                  wait_until="networkidle", timeout=30000)
        wide.wait_for_timeout(600)
        wide.screenshot(path=str(SHOTS / "page_desktop.png"))

        # телефон в светлой теме
        page.click("#theme-btn")
        page.wait_for_timeout(300)
        page.screenshot(path=str(SHOTS / "page_iphone_light.png"))
        browser.close()

    print(f"🖼️ Скриншоты: {SHOTS}")
    if errors:
        print("❗ Проблемы:", *errors, sep="\n  - ")
        return 1
    print("✅ E2E: страница жива, карточки рисуются, фильтры работают")
    return 0


if __name__ == "__main__":
    sys.exit(main())
