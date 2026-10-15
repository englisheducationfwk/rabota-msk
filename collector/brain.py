# -*- coding: utf-8 -*-
"""🧠 Мозг: отсев ложных «горничных» и оценка «выгоды» — без LLM, только
правила (бесплатно и предсказуемо).

Две работы:
    1. РЕЛЕВАНТНОСТЬ: оставить вакансии про домашний труд (горничная,
       уборщица, домработница, клининг…) и выкинуть чужие — «курьер»,
       «доставка», «водитель», «грузчик», «промоутер», «продавец»…,
       которые Авито подмешивает под словом «горничная».
       Плюс отсев резюме («ищу работу») — это соискатели, не вакансии.
    2. ОЦЕНКА 0–100: зарплата, неофициальное оформление (она это ищет),
       рейтинг работодателя по отзывам, свежесть, жильё/питание,
       «кадровое агентство» — минус. У каждой оценки — причины списком,
       чтобы в карточке показать «Почему такая оценка».
"""

from __future__ import annotations

import re

# --- словари ----------------------------------------------------------------
# Целевые слова: по ним вакансия вообще считается «нашей».
TARGET_WORDS = (
    "горничн", "уборщ", "уборк", "домработн", "клининг", "клинер",
    "housekeep", "хаускип", "посудомой", "прачк", "прачечн", "сиделк",
    "прислуг", "домоупр", "хозяйк", "нянечк", "няня",
)

# Признаки «не наша» вакансия — курьерские/складские/продажные подлоги.
FALSE_WORDS = (
    "курьер", "доставк", "водител", "грузчик", "промоутер", "мерчендайз",
    "раскладчик", "комплектовщик", "кладовщик", "склад", "оператор колл",
    "продавец", "консультант", "кассир", "официант", "бармен", "повар",
    "кухонный работник", "мойщик посуд", "мойщик", "автомой",
    "грузоперевозк", "перевозк", "такси", "яндекс", "пеший", "авто-курьер",
    "развоз", "разъезд", "разнорабоч", "строител", "монтажник", "сварщик",
    "электрик",
    "охранник", "сторож", "контролер", "мастер участк", "механик",
    "менеджер по продаж", "торговый представитель", "агент по недвижим",
    "риэлтор", "страховой агент", "промо", "дегустат", "анкетиров",
)

# «Сильно чужие» слова для описания: если их в тексте набирается много —
# это курьерская вакансия под маской горничной — частая подмена.
STRONG_FALSE_WORDS = (
    "курьер", "доставк", "водител", "такси", "грузчик", "развоз",
    "промоутер", "пеший", "личный автомобил", "личном автомобил",
    "личным автомобил", "своё авто", "свое авто", "свой автомобил",
    "на своём авто", "на своем авто", "на личном авто", "своя машин",
    "свою машин", "вождение",
)

# «Резюме» и предложения услуг — тоже мимо (нужны вакансии).
RESUME_WORDS = (
    "ищу работу", "ищу подработ", "предлагаю услуги", "резюме",
    "готова работать", "готова приступ", "ищу вакансию", "в поиске работы",
)

# Неофициальное оформление (то, что она ищет) — плюс к оценке.
UNOFFICIAL_WORDS = (
    "без оформлен", "неофициальн", "не оформля", "без трудов", "без тк",
    "на руки", "наличным", "ежедневн", "за смену", "за сутки", "подработ",
    "шабашк", "вахт", "без опыта",
)
OFFICIAL_WORDS = (
    "оформление по тк", "официальн", "трудовой договор", "самозанят",
    "тк рф", "социальный пакет", "отпуск", "больничный",
)

# Бонусы условий.
HOUSE_WORDS = ("проживани", "общежити", "жиль", "питани", "кормят", "квартир")
AGENCY_WORDS = ("кадровое агентств", "агентств", "подбор персонал",
                "группа компаний", "сеть отелей", "клинингов", "клининговая")

_SALARY_GOOD = 80000     # ₽/мес — от этого считаем «денежно»
_SALARY_MIN = 45000      # ниже — тревожный звонок


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def _hits(text: str, words: tuple[str, ...]) -> list[str]:
    return [w for w in words if w in text]


def analyze(item: dict) -> dict:
    """🎯 Вердикт по вакансии: relevant + score 0–100 + reasons + флаги.

    item — нормализованная карточка из avito.normalize_item()
    (плюс, если загружались, description/params/rating из .details()).
    Возвращает копию с добавленными полями.
    """
    title = _norm(item.get("title"))
    body = _norm(item.get("description"))
    text = f"{title} ␟ {body}"
    params_text = " ".join(f"{n} {v}" for n, v in item.get("params") or []).lower()
    everything = f"{text} {params_text}"

    target_hits = _hits(everything, TARGET_WORDS)
    title_target = _hits(title, TARGET_WORDS)
    title_false = _hits(title, FALSE_WORDS)
    strong_false = _hits(body, STRONG_FALSE_WORDS)
    resume_hits = _hits(everything, RESUME_WORDS)
    # сколько раз тема уборки реально звучит в описании (не «вскользь»)
    desc_mentions = sum(body.count(w) for w in TARGET_WORDS)

    relevant = True
    reasons: list[tuple[int, str]] = []

    # --- релевантность ---
    if resume_hits:
        relevant = False
        reasons.append((-100, "Это резюме соискателя, не вакансия"))
    elif not target_hits:
        relevant = False
        reasons.append((-100, "Нет ни одного слова про уборку/дом"))
    elif title_false and not title_target:
        relevant = False
        reasons.append((-100, f"Заголовок не про дом: {title_false[0]}…"))
    elif title_false and title_target:
        # «Горничная-курьер», «Уборщица-промоутер» — та самая подмена,
        # когда под словом «горничная» прячется курьер
        relevant = False
        reasons.append((-100, f"Смешанный заголовок ({title_false[0]}…) — "
                              f"похоже, работа не про уборку"))
    elif not title_target and desc_mentions < 2:
        # в заголовке уборки нет и в описании она упомянута вскользь
        relevant = False
        reasons.append((-100, "Уборка упомянута вскользь — скорее всего, "
                              "это другая работа"))
    elif len(strong_false) >= 2 and not title_false:
        # в заголовке «горничная», а в описании — доставка на личном авто…
        relevant = False
        reasons.append((-100, f"Описание про другое: "
                              f"{', '.join(strong_false[:2])}…"))
    elif strong_false:
        reasons.append((-10, f"В описании мелькает «{strong_false[0]}» — "
                             f"посмотрите внимательно"))

    # --- оценка ---
    score = 50
    salary = item.get("salary") or {}
    month = int(salary.get("month") or 0)
    if month >= _SALARY_GOOD:
        score += 20
        reasons.append((+20, f"Оплата {salary.get('text')} — хорошо для рынка"))
    elif month >= 60000:
        score += 10
        reasons.append((+10, f"Оплата {salary.get('text')}"))
    elif month:
        if month < _SALARY_MIN:
            score -= 15
            reasons.append((-15, "Оплата ниже 45 000 ₽/мес"))
        else:
            score += 2
            reasons.append((+2, f"Оплата {salary.get('text')}"))
    else:
        score -= 8
        reasons.append((-8, "Зарплата не указана"))

    if _hits(everything, UNOFFICIAL_WORDS):
        score += 15
        found = _hits(everything, UNOFFICIAL_WORDS)[:2]
        reasons.append((+15, f"Без оформления / на руки ({', '.join(found)})"))
    if _hits(everything, OFFICIAL_WORDS) and not _hits(
            everything, UNOFFICIAL_WORDS):
        score -= 5
        reasons.append((-5, "Только официальное оформление"))

    rating = item.get("rating") or {}
    if rating.get("score"):
        rs = float(rating["score"])
        reviews = int(rating.get("reviews") or 0)
        if rs >= 4.5 and reviews >= 5:
            score += 15
            reasons.append((+15, f"Рейтинг работодателя {rs} ({reviews} отз.)"))
        elif rs >= 4.0:
            score += 8
            reasons.append((+8, f"Рейтинг работодателя {rs} ({reviews} отз.)"))
        elif rs < 3.5 and reviews >= 3:
            score -= 12
            reasons.append((-12, f"Низкий рейтинг {rs} ({reviews} отз.)"))
    else:
        score -= 3
        reasons.append((-3, "Нет отзывов о работодателе"))

    if _hits(everything, AGENCY_WORDS) and _hits(title, AGENCY_WORDS):
        score -= 8
        reasons.append((-8, "Кадровое агентство / клининговая сеть"))

    # свежесть — отдельным весом, чтобы вверху всегда было живое
    fresh_min = item.get("fresh_min")
    if fresh_min is not None:
        if fresh_min <= 60:
            score += 10
            reasons.append((+10, "Опубликовано только что"))
        elif fresh_min <= 24 * 60:
            score += 5
            reasons.append((+5, "Свежая вакансия (сегодня)"))

    score = max(0, min(100, score))
    out = dict(item)
    out["relevant"] = relevant
    out["score"] = score
    out["reasons"] = [f"{'+' if w > 0 else ''}{w}, {t}"
                      for w, t in reasons if t]
    out["salary_month"] = month
    out["unofficial"] = bool(_hits(everything, UNOFFICIAL_WORDS))
    out["housing"] = bool(_hits(everything, HOUSE_WORDS))
    return out
