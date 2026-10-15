# -*- coding: utf-8 -*-
"""🚜 Цикл сбора: Авито → мозг → база → JSON → GitHub (→ Telegram).

Один цикл:
    1) страж: интернет должен видеть нас как Россию (мимо Happ);
    2) мостик и браузер (профиль с куками после ручного входа);
    3) поиск по запросам из настроек (Москва, «Работа», свежие сверху);
    4) новые карточки → «детали» (описание, оформление, рейтинг) — но
       не больше лимита за цикл (вежливость);
    5) мозг: отсев ложных «горничных» + оценка «выгоды» с причинами;
    6) база SQLite + срез для страницы мамы (data/vacancies.json).
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
    found = relevant = fresh = 0
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
                            "SELECT description FROM vacancies WHERE id=?",
                            (item["id"],)).fetchone()
                        is_new = row is None
                        has_desc = bool((row[0] if row else "") or "")
                        if (is_new or not has_desc) \
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

        payload = store.export_site(con, fresh_since)
        store.log_run(con, found, relevant, fresh)
        log(f"   🧠 Подходящих: {relevant}, из них новых: {fresh}")
        return {"found": found, "relevant": relevant, "fresh": fresh,
                "new_items": new_items, "payload": payload}
    finally:
        con.close()


def run_once(cfg: dict, session) -> dict:
    """▶️ Один цикл со стражем РУ-IP и всей обвязкой."""
    state = {"state": "idle", "message": "", "found": 0, "relevant": 0,
             "fresh": 0, "last_run": int(time.time()),
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
                      "fresh": stats["fresh"], "message": "сбор прошёл"})
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
    interval = max(5, int(cfg.get("interval_min") or 15))

    session = make_session()
    if args.once:
        state = run_once(cfg, session)
        return 0 if state.get("state") == "ok" else 1

    log(f"🚜 Работа MSK запущена. Период: {interval} мин. "
        f"Запросов: {len(cfg.get('queries') or [])}")
    while True:
        state = run_once(cfg, session)
        wait = interval * 60
        if state.get("state") in ("firewall", "tunnel"):
            wait = min(wait, 30 * 60)  # после заслона не частим
        log(f"😴 Следующий цикл через {wait // 60} мин")
        # сон кусками, чтобы панель могла остановить процесс по Ctrl+C
        end = time.time() + wait
        while time.time() < end:
            time.sleep(5)
        cfg = settings.load()  # настройки могли поменять из панели


if __name__ == "__main__":
    sys.exit(main())
