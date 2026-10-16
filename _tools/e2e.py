# -*- coding: utf-8 -*-
"""🖥️ E2E: страница на локальном сервере + скриншоты.

Кладёт демо-данные (или реальный срез из data/vacancies.json, если он
есть), поднимает http на 8788 поверх docs/ и снимает скриншоты:
iPhone-вид (390x844) и широкий — плюс проверяет, что страница жива:
два меню («Новые» / «Просмотренные»), отметка ✅ при прокрутке,
порции по 30, фильтры.

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
PER = 30      # порция карточек — как в docs/app.js


def demo_payload() -> dict:
    """🎭 Демо-вакансии: разные случаи, как в жизни (для проверки вида).

    Плюс хвост из сгенерированных: с ним видно порции по 30 и оба меню.
    """
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
             last_seen=now - 60,
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
             last_seen=now - 3600,
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
             last_seen=now - 3600 * 25,
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
             last_seen=now - 3600 * 49,
             rating={}, employer_id="", status="new", query="горничная вахта"),
    ]
    # Хвост: 46 штук — с ним видно порции по 30 и оба меню.
    # Первые десять — «просмотренные» (status seen): их засеем в localStorage
    # и посмотрим, как живёт меню «Просмотренные».
    stations = ["Тёплый Стан", "Беляево", "Юго-Западная", "Проспект Мира",
                "Курская", "Бауманская", "Сокол", "Речной вокзал",
                "Домодедовская", "Отрадное", "Медведково", "Планерная"]
    for i in range(46):
        first = now - (i + 1) * 3600 * 3
        viewed = i < 10
        items.append(dict(
            id=str(105 + i),
            title="Уборщица в офис, " + stations[i % len(stations)],
            url="https://www.avito.ru/demo/" + str(105 + i),
            price=str(40 + i) + " 000 ₽",
            salary_month=(40 + i) * 1000, salary_unit="месяц",
            employer=("Клининговая компания №" + str(i + 1)) if i % 3 else "",
            metro="м. " + stations[i % len(stations)], address="Москва",
            published=first - 1800, published_text="",
            description=("Уборка офисных помещений. График 5/2, "
                         "оформление по ТК. Оплата два раза в месяц."),
            score=40 + (i * 7) % 55, reasons=["+10, Оплата указана"],
            unofficial=(i % 4 == 0), housing=(i % 5 == 0),
            first_seen=first,
            last_seen=(first + 7200 if viewed else first),
            rating=({"score": round(4.0 + (i % 10) / 10, 1), "reviews": i * 3}
                    if i % 2 else {}),
            employer_id=str(200 + i) if i % 3 else "",
            status="seen" if viewed else "new", query="уборщица",
        ))
    return {"updated": now, "new_since": 0, "count": len(items),
            "items": items}


def main() -> int:
    use_demo = "--demo" in sys.argv or not DATA.exists()
    if use_demo:
        payload = demo_payload()
        DATA.parent.mkdir(parents=True, exist_ok=True)
        DATA.write_text(json.dumps(payload, ensure_ascii=False),
                        encoding="utf-8")
        print("🎭 Демо-данные разложены")
    else:
        payload = json.loads(DATA.read_text(encoding="utf-8"))

    # «Просмотренные» с телефона: засеваем те, что в базе уже со статусом seen
    seen_ids = {it["id"] for it in payload.get("items", [])
                if it.get("status") == "seen"}
    seed = json.dumps(json.dumps({i: 1 for i in sorted(seen_ids)}))

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(DOCS))
    httpd = ThreadingHTTPServer(("127.0.0.1", 8788), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print("🌐 Локальный сервер: http://127.0.0.1:8788/")

    def hermetic(ctx) -> None:
        """🚧 Мимо GitHub: проверяем местный файл, а не живой срез с сети."""
        ctx.route("**api.github.com**", lambda route: route.abort())
        ctx.route("**raw.githubusercontent.com**", lambda route: route.abort())

    SHOTS.mkdir(exist_ok=True)
    from playwright.sync_api import sync_playwright
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # iPhone-вид
        ctx = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2, is_mobile=True, has_touch=True,
            user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like "
                        "Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
                        "Version/17.0 Mobile/15E148 Safari/604.1"),
        )
        ctx.add_init_script(
            "try{localStorage.setItem('msk_viewed', " + seed + ")}catch(e){}")
        hermetic(ctx)
        page = ctx.new_page()
        console_errors: list[str] = []
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        def cards() -> int:
            return page.locator(".card").count()

        def num(sel: str) -> int:
            return int(page.inner_text(sel))

        def counts() -> tuple[int, int]:
            """Счётчики меню одним куском — оба сразу, из одного состояния.

            Читать их по одному нельзя: страница сама двигает счётчики
            (автоотметка ✅), и сумма из двух чтений не сходится.
            """
            return tuple(page.evaluate(
                "() => [+document.getElementById('cnt-new').textContent,"
                " +document.getElementById('cnt-seen').textContent]"))

        def total() -> int:
            n, s = counts()
            return n + s

        def settle(ms: int = 800) -> None:
            """Дать странице успокоиться.

            Автоотметка ✅ дорисовывает значок в карточку и сдвигает её
            содержимое; кликать в этот момент нельзя — нажатие уедет мимо
            кнопки. Живому человеку это не грозит (он не жмёт кнопку в ту же
            секунду, что пересобрался список), а вот тесту — вполне.
            """
            page.wait_for_timeout(ms)

        page.goto("http://127.0.0.1:8788/index.html",
                  wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1200)   # больше DWELL — автоотметка успевает
        cards1 = cards()
        n_new, n_seen = counts()
        print(f"📱 Меню «Новые»: карточек {cards1}, новых {n_new}, "
              f"просмотренных {n_seen}")
        if cards1 == 0:
            errors.append("карточки не отрисовались")
        if cards1 > PER:
            errors.append(f"за раз показано больше {PER} карточек: {cards1}")
        if seen_ids and n_seen < len(seen_ids):
            errors.append(f"«Просмотренные»: ждали минимум {len(seen_ids)}, "
                          f"видим {n_seen}")
        if console_errors:
            errors.append("ошибки JS: " + "; ".join(console_errors[:3]))
        page.screenshot(path=str(SHOTS / "page_iphone.png"))

        # прокрутка: карточки сами становятся «просмотренными»
        before = counts()[0]
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(900)
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(900)
        after = counts()[0]
        marked = page.locator(".card.is-viewed").count()
        print(f"📱 После прокрутки: новых {before} → {after}, "
              f"карточек с ✅ в кадре: {marked}")
        if after >= before:
            errors.append("прокрутка не отметила карточки просмотренными")
        if marked == 0:
            errors.append("нет карточек со значком ✅ после прокрутки")
        page.screenshot(path=str(SHOTS / "page_iphone_scroll.png"))
        to_top = page.evaluate("!document.getElementById('to-top').hidden")
        if not to_top:
            errors.append("кнопка «наверх» не показалась при прокрутке")

        # порция «Показать ещё»
        if page.locator("#more-btn").is_visible():
            page.locator("#more-btn").scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            page.screenshot(path=str(SHOTS / "page_iphone_more.png"))
            page.locator("#more-btn").click()
            page.wait_for_timeout(500)
            cards2 = cards()
            print(f"📱 «Показать ещё»: {cards1} → {cards2} карточек")
            if cards2 <= cards1:
                errors.append("«Показать ещё» не добавил карточек")
            if use_demo and page.locator("#more-btn").is_visible():
                errors.append("«Показать ещё» осталась, хотя показаны все")
        else:
            print("📱 «Показать ещё» не понадобилась (данных меньше порции)")

        # меню «Просмотренные» — пересборка списка
        page.click('[data-tab="seen"]')
        page.wait_for_timeout(500)
        seen_cards = cards()
        seen_badges = page.locator(".card .badge.seen").count()
        seen_counter = counts()[1]
        print(f"📱 Меню «Просмотренные»: карточек {seen_cards}, "
              f"счётчик {seen_counter}")
        if seen_cards == 0:
            errors.append("меню «Просмотренные» пустое")
        if seen_badges != seen_cards:
            errors.append("не у всех просмотренных карточек значок ✅")
        page.screenshot(path=str(SHOTS / "page_tab_seen.png"))

        page.click('[data-tab="new"]')
        page.wait_for_timeout(500)
        back = cards()
        left_new = counts()[0]
        print(f"📱 «Новые» после пересборки: карточек {back}, "
              f"счётчик {left_new}")
        # карточек ровно min(30, непросмотренные) + 1–2, отметившиеся в кадре
        if back > PER or back < min(PER, left_new):
            errors.append(f"«Новые» не сошлись со счётчиком: карточек {back}, "
                          f"новых {left_new}")

        # фильтр «без оформления»
        t0 = total()
        page.click('[data-filter="unofficial"]')
        page.wait_for_timeout(400)
        t1 = total()
        print(f"📱 Фильтр «без оформления»: {t0} → {t1}")
        if t1 == 0 or t1 >= t0:
            errors.append("фильтр «без оформления» ничего не изменил")
        page.screenshot(path=str(SHOTS / "page_filter_unofficial.png"))
        page.click('[data-filter="unofficial"]')  # снять фильтр
        settle()

        # «Не подходит» — карточка исчезает сразу
        t2 = total()
        page.click('.card .hide-act')
        page.wait_for_timeout(400)
        t3 = total()
        print(f"📱 «Не подходит»: {t2} → {t3}")
        if t3 >= t2:
            errors.append("«Не подходит» не убрал карточку")

        # «Заблокировать» — с подтверждением
        page.on("dialog", lambda d: d.accept())
        settle()
        page.click('.card .block-act')
        page.wait_for_timeout(400)
        t4 = total()
        unblock = page.locator("#unblock-chip").count()
        print(f"📱 После блокировки: вакансий {t4}, "
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
        hermetic(wide.context)
        wide.goto("http://127.0.0.1:8788/index.html",
                  wait_until="networkidle", timeout=30000)
        wide.wait_for_timeout(800)
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
    print("✅ E2E: страница жива, меню и отметки работают, фильтры на месте")
    return 0


if __name__ == "__main__":
    sys.exit(main())
