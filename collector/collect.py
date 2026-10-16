# -*- coding: utf-8 -*-
"""🚜 Цикл сбора: Авито → мозг → база → JSON → GitHub (→ Telegram).

Один цикл:
    1) страж: интернет должен видеть нас как Россию (мимо Happ);
    2) мостик и браузер (профиль с куками после ручного входа);
    3) поиск по запросам из настроек (Москва, «Работа», свежие сверху);
    4) новые карточки → «детали» (описание, оформление, рейтинг) — но
       не больше лимита за цикл (вежливость);
    5) мозг: отсев ложных «горничных» + оценка «выгоды» с причинами;
    6) база SQLite + срез для страницы (data/vacancies.json).
    7) публикация на GitHub (+ Telegram-дайджест, если включён).

Запуск:
    python collector/collect.py --once    # один цикл (для проверки)
    python collector/collect.py            # цикл + автосбор каждые N минут
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collector import brain, notify, publish, settings, store  # noqa: E402
from collector.avito import AvitoBrowser, Firewall, polite_sleep  # noqa: E402
from collector.netguard import (BRIDGE_PORT, check_ru,  # noqa: E402
                                ensure_bridge, make_session)


def log(msg: str) -> None:
    """🖨️ Строчка журнала (панель читает stdout)."""
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def collect_flow(cfg: dict) -> dict:
    """🚜 Полный обход Авито и запись в базу (внутри одного цикла)."""
    con = store.connect()
    found = relevant = fresh = updated = 0
    collected: list[tuple[dict, bool]] = []
    ensure_bridge()
    try:
        with AvitoBrowser(store.PROFILE_DIR, log=log,
                          headless=bool(cfg.get("headless")),
                          bridge_port=BRIDGE_PORT,
                          samples_dir=store.SAMPLES_DIR) as browser:
            seen: set[str] = set()
            details_left = int(cfg.get("details_limit") or 12)
            queries = [q.strip() for q in (cfg.get("queries") or [])
                       if q.strip()]
            pages = max(1, int(cfg.get("pages_per_query") or 1))

            for query in queries:
                for page in range(1, pages + 1):
                    try:
                        items = browser.search(query, page=page)
                    except Firewall:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        log(f"   ⚠️ «{query}» стр.{page}: "
                            f"{type(exc).__name__} {str(exc)[:120]}")
                        continue
                    for item in items:
                        if not item["id"] or item["id"] in seen:
                            continue
                        seen.add(item["id"])
                        found += 1
                        row = con.execute(
                            "SELECT description, published_text FROM "
                            "vacancies WHERE id=?",
                            (item["id"],)).fetchone()
                        is_new = row is None
                        has_desc = bool((row[0] if row else "") or "")
                        has_pub = bool((row[1] if row else "") or "")
                        if (is_new or not has_desc or not has_pub) \
                                and item["url"].startswith("http") \
                                and details_left > 0:
                            try:
                                details = browser.details(item["url"])
                                item["description"] = (
                                    details["description"]
                                    or item["description"])
                                item["params"] = details["params"]
                                if details.get("rating"):
                                    item["rating"] = details["rating"]
                                if details.get("employer"):
                                    item["employer"] = details["employer"]
                                if details.get("published_ts"):
                                    item["published_ts"] = \
                                        details["published_ts"]
                                    item["published_text"] = \
                                        details.get("published_text") or ""
                                details_left -= 1
                                polite_sleep()
                            except Firewall:
                                raise
                            except Exception as exc:  # noqa: BLE001
                                log(f"   ⚠️ детали {item['id']}: "
                                    f"{type(exc).__name__}")
                        if not item.get("rating") and item.get("employer_id"):
                            cached = store.known_employer(
                                con, item["employer_id"])
                            if cached:
                                item["rating"] = cached
                        collected.append((item, is_new))
                    polite_sleep()

        log(f"   🧾 Собрано карточек: {found}")
        fresh_since = store.new_since(con)
        now = int(time.time())
        new_items: list[dict] = []
        for item, _is_new in collected:
            ts = int(item.get("published_ts") or 0) or now
            item["fresh_min"] = max(0, (now - ts) // 60)
            verdict = brain.analyze(item)
            if item.get("rating") and item.get("employer_id"):
                store.remember_employer(con, item["employer_id"],
                                        item.get("employer") or "",
                                        item["rating"])
            was_new = store.upsert(con, verdict)
            if verdict["relevant"]:
                relevant += 1
                if was_new:
                    fresh += 1
                    new_items.append(verdict)
                else:
                    updated += 1

        payload = store.export_site(con, fresh_since)
        store.log_run(con, found, relevant, fresh)
        log(f"   🧠 Подходящих: {relevant} · новых: {fresh} · "
            f"обновлено: {updated}")
        return {"found": found, "relevant": relevant, "fresh": fresh,
                "updated": updated,
                "new_items": new_items, "payload": payload}
    finally:
        con.close()


def run_once(cfg: dict, session) -> dict:
    """▶️ Один цикл со стражем РУ-IP и всей обвязкой."""
    state = {"state": "idle", "message": "", "found": 0, "relevant": 0,
             "fresh": 0, "updated": 0, "last_run": int(time.time()),
             "next_run": int(time.time())
             + max(5, int(cfg.get("interval_min") or 15)) * 60}
    ok, message = check_ru(session)
    state["ip"] = message
    if not ok:
        state.update({"state": "tunnel", "message": message})
        store.save_status(state)
        log(f"⛔ {message}")
        return state
    log(f"🛡️ {message}")
    try:
        stats = collect_flow(cfg)
        state.update({"state": "ok", "found": stats["found"],
                      "relevant": stats["relevant"],
                      "fresh": stats["fresh"],
                      "updated": stats["updated"],
                      "message": "сбор прошёл"})
        if cfg.get("publish") and cfg.get("repo_url"):
            ok_pub, info = publish.publish(cfg["repo_url"],
                                           cfg.get("repo_branch") or "data",
                                           stats["payload"], log=log)
            state["publish"] = info if ok_pub else f"ошибка: {info}"
            if not ok_pub:
                log(f"   ⚠️ Публикация: {info}")
        token = str(cfg.get("telegram_token") or "")
        chat = str(cfg.get("telegram_chat") or "")
        if token and chat and stats["new_items"]:
            text = notify.digest(stats["new_items"],
                                 cfg.get("site_url") or "")
            ok_tg, info = notify.send(token, chat, text)
            state["telegram"] = info if ok_tg else f"ошибка: {info}"
            if ok_tg:
                log(f"   📣 Telegram: {info}")
    except Firewall as exc:
        state.update({"state": "firewall", "message": str(exc)})
        log(f"⛔ {exc}")
    except Exception as exc:  # noqa: BLE001
        state.update({"state": "error",
                      "message": f"{type(exc).__name__}: {exc}"})
        log(f"⛔ Ошибка цикла: {type(exc).__name__}: {exc}")
    store.save_status(state)
    return state


def is_active_now(cfg: dict, now: time.struct_time | None = None) -> bool:
    """🕐 Можно ли собирать прямо сейчас (по режиму и часам)."""
    now = now or time.localtime()
    mode = str(cfg.get("mode") or "daily")
    if mode == "frequent":
        start = int(cfg.get("active_from") or 8)
        end = int(cfg.get("active_to") if cfg.get("active_to") is not None
                  else 24)
        hour = now.tm_hour
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end
    # daily: по умолчанию — только в заданные часы, но первый запуск
    # (при включении сервера) собираем сразу — этого хочет пользователь
    return True


def _nearest_daily_wait(cfg: dict, seconds_now: int) -> int:
    """⏰ Секунд до ближайшего «часа сбора» (daily-режим)."""
    hours = sorted(int(h) for h in (cfg.get("daily_hours") or [10, 19]))
    best: int | None = None
    for hour in hours:
        left = hour * 3600 - seconds_now
        if left <= 60:  # этот час уже прошёл (или наступит через секунду)
            left += 86400
        if best is None or left < best:
            best = left
    return (best or 86400) + 60


def wait_seconds(cfg: dict, state: dict) -> int:
    """⏰ Сколько спать до следующего цикла.

    Режим daily (по умолчанию): сбор 2 раза в день — в часы daily_hours
    (по умолчанию 10:00 и 19:00 — утро и вечер, когда публикуют больше).
    Режим frequent (доп. свитч): те же 2 раза плюс каждые interval_min
    минут с active_from до active_to (ночью спим).
    """
    mode = str(cfg.get("mode") or "daily")
    now = time.localtime()
    seconds_now = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec
    if mode == "frequent":
        interval = max(5, int(cfg.get("interval_min") or 15))
        wait = interval * 60
        start = int(cfg.get("active_from") or 8)
        end = int(cfg.get("active_to") if cfg.get("active_to") is not None
                  else 24)
        if end < 24:
            gap = end * 3600 - seconds_now
            if gap <= 0:
                wait = _nearest_daily_wait(cfg, seconds_now)
            else:
                wait = min(wait, max(60, gap))
        elif not is_active_now(cfg, now):
            wait = _nearest_daily_wait(cfg, seconds_now)
    else:
        wait = _nearest_daily_wait(cfg, seconds_now)
    if state.get("state") in ("firewall", "tunnel"):
        wait = min(wait, 30 * 60)  # после заслона не частим
    return wait


def _schedule_signature(cfg: dict) -> tuple:
    """🧾 Отпечаток расписания: если поменялся — перечитываем настройки."""
    return (str(cfg.get("mode") or "daily"),
            int(cfg.get("interval_min") or 15),
            int(cfg.get("active_from") or 8),
            int(cfg.get("active_to") if cfg.get("active_to") is not None
                else 24),
            tuple(int(h) for h in (cfg.get("daily_hours") or [10, 19])))


def main() -> int:
    parser = argparse.ArgumentParser(description="Работа MSK: сбор Авито")
    parser.add_argument("--once", action="store_true",
                        help="один цикл и выход")
    parser.add_argument("--interval", type=int, default=0,
                        help="переопределить интервал, минут")
    args = parser.parse_args()

    cfg = settings.load()
    if args.interval:
        cfg["interval_min"] = args.interval

    session = make_session()
    if args.once:
        state = run_once(cfg, session)
        return 0 if state.get("state") == "ok" else 1

    mode = str(cfg.get("mode") or "daily")
    if mode == "frequent":
        mode_text = (f"каждые {int(cfg.get('interval_min') or 15)} мин "
                     f"({cfg.get('active_from')}:00–{cfg.get('active_to')}:00)"
                     f" + утро/вечер")
    else:
        hours = ", ".join(f"{int(h)}:00" for h in
                          (cfg.get("daily_hours") or [10, 19]))
        mode_text = f"2 раза в день ({hours})"
    log(f"🚜 Работа MSK запущена. Режим: {mode_text}. "
        f"Запросов: {len(cfg.get('queries') or [])}")

    first = True
    while True:
        if not first and not is_active_now(cfg):
            wait = wait_seconds(cfg, {"state": "idle"})
            hours, mins = wait // 3600, (wait % 3600) // 60
            store.save_status({"state": "idle",
                               "message": "Ночная пауза — утром всё соберу",
                               "next_run": int(time.time()) + wait})
            log(f"🌙 Ночь: сплю до ближайшего часа сбора "
                f"({hours} ч {mins} мин)")
        else:
            first = False
            state = run_once(cfg, session)
            wait = wait_seconds(cfg, state)
            hours, mins = wait // 3600, (wait % 3600) // 60
            log(f"😴 Следующий цикл через {hours} ч {mins} мин")
        # сон кусками; раз в 30 секунд сверяем расписание из настроек
        signature = _schedule_signature(cfg)
        end = time.time() + wait
        last_check = time.time()
        while time.time() < end:
            time.sleep(5)
            if time.time() - last_check >= 30:
                last_check = time.time()
                fresh = settings.load()
                if _schedule_signature(fresh) != signature:
                    log("⚙️ Расписание изменилось — перечитываю настройки.")
                    cfg = fresh
                    break
        else:
            cfg = settings.load()  # настройки могли поменять из панели


if __name__ == "__main__":
    sys.exit(main())
