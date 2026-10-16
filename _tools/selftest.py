# -*- coding: utf-8 -*-
"""✅ Самопроверка офлайн: мозг, зарплаты, база, вид среза для страницы.

Никакого интернета — только фикстуры. Запуск:
    python _tools/selftest.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collector import brain, store  # noqa: E402
from collector.avito import parse_salary  # noqa: E402

CHECKS = 0
FAILS = 0


def check(name: str, got, expected) -> None:
    """🧪 Сравнить и сказать вслух (не бросать — хотим видеть все огрехи)."""
    global CHECKS, FAILS
    CHECKS += 1
    ok = got == expected
    if not ok:
        FAILS += 1
    mark = "✅" if ok else "❗"
    extra = "" if ok else f"  (получилось {got!r}, ждали {expected!r})"
    print(f"{mark} {name}{extra}")


def item(title: str, desc: str = "") -> dict:
    return dict(id="t", title=title, description=desc, price_text="",
                params=[], rating={}, fresh_min=30, salary={"month": 0})


def test_salary() -> None:
    print("\n💰 Зарплаты:")
    check("за смену", parse_salary("4 000 ₽ за смену")["month"], 84000)
    check("в месяц", parse_salary("90 000 ₽")["month"], 90000)
    check("в час", parse_salary("700 ₽ в час")["month"], 112000)
    check("диапазон — верх", parse_salary("50 000 – 70 000 ₽")["month"], 70000)
    check("нет цифр", parse_salary("по договорённости")["month"], None)
    check("единица", parse_salary("1 200 ₽ за сутки")["unit"], "сутки")


def test_brain() -> None:
    print("\n🧠 Мозг (отсев и оценки):")
    cases = [
        ("Горничная в отель, 4 000 ₽ за смену",
         "Уборка номеров. Без оформления, оплата на руки каждый день.", True),
        ("Курьер-горничная с личным автомобилем", "Доставка заказов.", False),
        ("Горничная", "Развоз товара по адресам, свой автомобиль.", False),
        ("Уборщица в офис", "Официальное оформление по ТК РФ.", True),
        ("Резюме: ищу работу горничной", "Опыт 10 лет.", False),
        ("Оператор call-центра", "Горничная не нужна, офис.", False),
        ("Домработница в семью", "Уборка квартиры, глажка, готовка.", True),
        ("Промоутер-уборщица", "Раздача листовок в ТЦ.", False),
    ]
    for title, desc, expect in cases:
        v = brain.analyze(item(title, desc))
        check(title[:44], v["relevant"], expect)

    v = brain.analyze(dict(
        item("Горничная", "Уборка без оформления"),
        salary={"month": 105000, "unit": "смена"},
        rating={"score": 4.8, "reviews": 23}, fresh_min=10,
        unofficial=True, housing=True))
    check("оценка высокой вакансии ≥ 80", v["score"] >= 80, True)
    check("причины непустые", len(v["reasons"]) >= 3, True)

    v2 = brain.analyze(item("Уборщица", "Уборка помещений"))
    check("оценка без всего — средняя", 40 <= v2["score"] <= 60, True)


def test_store() -> None:
    print("\n🗄️ База и срез для страницы:")
    db_backup = store.DB_PATH
    exp_backup = store.EXPORT_PATH
    try:
        store.DB_PATH = store.DATA_DIR / "selftest.db"
        store.EXPORT_PATH = store.DATA_DIR / "selftest_export.json"
        store.DB_PATH.unlink(missing_ok=True)
        con = store.connect()
        raw = dict(
            item("Горничная в отель", "Уборка номеров"),
            price_text="5 000 ₽ за смену",
            salary={"month": 105000, "unit": "смена"},
            rating={"score": 4.8, "reviews": 23},
            employer="Отель", employer_id="1", metro="м. Тверская",
            url="https://www.avito.ru/x", published_ts=0)
        v = brain.analyze(raw)
        check("первая запись — новая", store.upsert(con, v), True)
        check("повтор — не новая", store.upsert(con, v), False)
        payload = store.export_site(con, fresh_since=0)
        check("в срезе 1 вакансия", payload["count"], 1)
        it = payload["items"][0]
        for field in ("id", "title", "price", "salary_month", "score",
                      "reasons", "first_seen", "last_seen", "url"):
            check(f"поле «{field}» есть", field in it, True)
        check("рейтинг дожил", it["rating"]["score"], 4.8)
        check("повтор — status стал seen", it["status"], "seen")
        check("last_seen не раньше first_seen",
              it["last_seen"] >= it["first_seen"], True)
        con.close()
        store.DB_PATH.unlink(missing_ok=True)
        store.EXPORT_PATH.unlink(missing_ok=True)
    finally:
        store.DB_PATH = db_backup
        store.EXPORT_PATH = exp_backup


def main() -> int:
    print("🧪 Самопроверка «Работа MSK» (без интернета)")
    test_salary()
    test_brain()
    test_store()
    print(f"\n{'✅' if FAILS == 0 else '❗'} Итог: {CHECKS - FAILS} из "
          f"{CHECKS} проверок прошли")
    return 0 if FAILS == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
