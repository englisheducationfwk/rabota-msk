# -*- coding: utf-8 -*-
"""🗄️ База: SQLite (история и дедупликация) + JSON для страницы мамы.

SQLite держит всё, что видели: первую и последнюю встречу каждой вакансии,
описание, рейтинг работодателя, оценку мозга. Наружу (на страницу) уходит
только свежий срез — data/vacancies.json: последние 300 подходящих
вакансий, отсортированных по свежести. Пишем атомарно (tmp + replace).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "rabota.db"
EXPORT_PATH = DATA_DIR / "vacancies.json"
STATUS_PATH = DATA_DIR / "status.json"
COOKIES_PATH = DATA_DIR / "cookies.json"
PROFILE_DIR = DATA_DIR / "session" / "profile"
SAMPLES_DIR = DATA_DIR / "_samples"

SCHEMA = """
CREATE TABLE IF NOT EXISTS vacancies (
    id TEXT PRIMARY KEY,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    query TEXT,
    title TEXT,
    url TEXT,
    price_text TEXT,
    salary_month INTEGER,
    salary_unit TEXT,
    employer TEXT,
    employer_id TEXT,
    metro TEXT,
    address TEXT,
    published_ts INTEGER,
    description TEXT,
    params TEXT,
    rating_score REAL,
    rating_reviews INTEGER,
    score INTEGER,
    relevant INTEGER DEFAULT 1,
    reasons TEXT,
    unofficial INTEGER DEFAULT 0,
    housing INTEGER DEFAULT 0,
    status TEXT DEFAULT 'new',      -- new | seen | fav | hidden
    notified INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_v_last_seen ON vacancies(last_seen);
CREATE INDEX IF NOT EXISTS idx_v_score ON vacancies(score);

CREATE TABLE IF NOT EXISTS employers (
    id TEXT PRIMARY KEY,
    name TEXT,
    rating REAL,
    reviews INTEGER,
    checked_at INTEGER
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER, found INTEGER, relevant INTEGER, fresh INTEGER,
    note TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect() -> sqlite3.Connection:
    """🔌 Соединение с базой (создаёт файл и схему при первом запуске)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    return con


def upsert(con: sqlite3.Connection, item: dict) -> bool:
    """📥 Записать вакансию. True — если она новая (не виденная раньше)."""
    now = int(time.time())
    vid = str(item.get("id"))
    row = con.execute("SELECT id, employer_id, rating_score FROM vacancies "
                      "WHERE id=?", (vid,)).fetchone()
    salary = item.get("salary") or {}
    rating = item.get("rating") or {}
    common = (
        item.get("query"), item.get("title"), item.get("url"),
        item.get("price_text"), int(salary.get("month") or 0),
        str(salary.get("unit") or ""),
        item.get("employer"), item.get("employer_id"), item.get("metro"),
        item.get("address"), int(item.get("published_ts") or 0),
        item.get("description"), json.dumps(item.get("params") or [],
                                            ensure_ascii=False),
        rating.get("score"), int(rating.get("reviews") or 0),
        int(item.get("score") or 0), 1 if item.get("relevant") else 0,
        json.dumps(item.get("reasons") or [], ensure_ascii=False),
        1 if item.get("unofficial") else 0,
        1 if item.get("housing") else 0,
    )
    if row is None:
        con.execute("""INSERT INTO vacancies
            (first_seen, last_seen, query, title, url, price_text,
             salary_month, salary_unit, employer, employer_id, metro, address,
             published_ts, description, params, rating_score,
             rating_reviews, score, relevant, reasons, unofficial, housing, id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (now, now) + common + (vid,))
        con.commit()
        return True
    con.execute("""UPDATE vacancies SET last_seen=?, query=?, title=?,
        url=?, price_text=?, salary_month=?, salary_unit=?, employer=?,
        employer_id=?, metro=?, address=?, published_ts=?, description=?,
        params=?, rating_score=?, rating_reviews=?, score=?, relevant=?,
        reasons=?, unofficial=?, housing=? WHERE id=?""",
                (now,) + common + (vid,))
    con.commit()
    return False


def remember_employer(con: sqlite3.Connection, employer_id: str, name: str,
                      rating: dict) -> None:
    """⭐ Кэш работодателя, чтобы не ходить к нему дважды за неделю."""
    if not employer_id:
        return
    con.execute("""INSERT INTO employers (id, name, rating, reviews, checked_at)
        VALUES (?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET name=excluded.name,
            rating=excluded.rating, reviews=excluded.reviews,
            checked_at=excluded.checked_at""",
                (str(employer_id), name or "",
                 rating.get("score"), int(rating.get("reviews") or 0),
                 int(time.time())))
    con.commit()


def known_employer(con: sqlite3.Connection, employer_id: str,
                   max_age_days: int = 7) -> dict | None:
    """⭐ Рейтинг из кэша, если он свежее max_age_days, иначе None."""
    if not employer_id:
        return None
    row = con.execute("SELECT rating, reviews, checked_at FROM employers "
                      "WHERE id=?", (str(employer_id),)).fetchone()
    if row and int(time.time()) - int(row[2] or 0) < max_age_days * 86400:
        return {"score": row[0], "reviews": row[1]}
    return None


def log_run(con: sqlite3.Connection, found: int, relevant: int, fresh: int,
            note: str = "") -> None:
    """📝 Журнал циклов — панель показывает по нему историю."""
    con.execute("INSERT INTO runs (ts, found, relevant, fresh, note) "
                "VALUES (?,?,?,?,?)",
                (int(time.time()), found, relevant, fresh, note))
    con.commit()


def export_site(con: sqlite3.Connection, fresh_since: int) -> dict:
    """🌐 Срез для страницы мамы: последние подходящие, свежие сверху.

    fresh_since — отметка времени прошлого визита (что «новое»).
    Возвращает готовый словарь (он же пишется в JSON).
    """
    rows = con.execute("""
        SELECT id, title, url, price_text, salary_month, salary_unit,
               employer, metro, address, published_ts, description, score,
               reasons, unofficial, housing, first_seen, rating_score,
               rating_reviews, employer_id, status, query
        FROM vacancies
        WHERE relevant=1 AND status != 'hidden'
        ORDER BY first_seen DESC
        LIMIT 300""").fetchall()
    items = []
    for r in rows:
        items.append({
            "id": r[0], "title": r[1], "url": r[2],
            "price": r[3], "salary_month": r[4], "salary_unit": r[5],
            "employer": r[6], "metro": r[7], "address": r[8],
            "published": r[9],
            "description": (r[10] or "")[:1500], "score": r[11],
            "reasons": json.loads(r[12] or "[]"),
            "unofficial": bool(r[13]), "housing": bool(r[14]),
            "first_seen": r[15],
            "rating": ({"score": r[16], "reviews": r[17]} if r[16] else {}),
            "employer_id": r[18], "status": r[19], "query": r[20],
        })
    payload = {
        "updated": int(time.time()),
        "new_since": fresh_since,
        "count": len(items),
        "items": items,
    }
    save_json(EXPORT_PATH, payload)
    return payload


def save_json(path: Path, payload: dict) -> None:
    """💾 Атомарная запись JSON: tmp + os.replace (как принято в проекте)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)


def save_status(payload: dict) -> None:
    """📊 Статус для панели и страницы (последний цикл, ошибки, планы)."""
    payload = dict(payload)
    payload["ts"] = int(time.time())
    save_json(STATUS_PATH, payload)


def new_since(con: sqlite3.Connection) -> int:
    """🕐 Время последнего визита мамы (0 — ещё не заходила: всё новое)."""
    row = con.execute("SELECT value FROM meta WHERE key='last_visit'") \
        .fetchone()
    try:
        return int(row[0]) if row else 0
    except Exception:
        return 0


def set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    """📌 Записать метку (например, время последнего визита)."""
    con.execute("INSERT INTO meta (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)))
    con.commit()
