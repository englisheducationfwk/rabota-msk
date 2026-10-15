# -*- coding: utf-8 -*-
"""⚙️ Настройки проекта: один JSON-файл, который правится из панели.

Лежит в data/settings.json (в git не попадает). Если файла нет —
создаётся с разумными значениями по умолчанию.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SETTINGS_PATH = DATA_DIR / "settings.json"

DEFAULTS = {
    # Запросы к Авито (Москва, раздел «Работа», сортировка по дате).
    "queries": ["горничная", "горничная в отель", "уборщица",
                "домработница", "клининг", "горничная вахта"],
    "pages_per_query": 1,          # сколько страниц выдачи листать
    "min_salary_month": 0,         # отсекать вакансии дешевле (₽/мес, 0 = все)
    "interval_min": 15,            # период автосбора в режиме «каждые 15 минут»
    "mode": "daily",               # daily = 2 раза в день; frequent = каждые 15 минут
    "daily_hours": [10, 19],       # часы сбора в режиме «2 раза в день»
    "active_from": 8,              # режим «каждые 15 минут»: ночью спим…
    "active_to": 24,               # …и собираем с 8 утра до полуночи
    "details_limit": 12,           # максимум «деталей» за цикл (вежливость)
    "publish": True,               # отправлять данные на GitHub
    "repo_url": "",                # https://github.com/<user>/rabota-msk.git
    "repo_branch": "data",         # ветка с данными (один обновляемый коммит)
    "site_url": "",                # https://<user>.github.io/rabota-msk/
    "telegram_token": "",          # опция: пусто = выключено
    "telegram_chat": "",           # chat_id владельца (ловится кнопкой «Привязать»)
    "headless": False,             # Авито пропускает живой браузер, не headless
    "auto_start": True,            # при открытии панели сбор стартует сам
    "auto_restart": True,          # если сбор упал — поднять заново
}


def load() -> dict:
    """📥 Настройки с диска (недостающие ключи — из значений по умолчанию)."""
    cfg = dict(DEFAULTS)
    try:
        if SETTINGS_PATH.exists():
            stored = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                cfg.update(stored)
    except Exception:
        pass
    return cfg


def save(cfg: dict) -> None:
    """💾 Сохранить настройки (атомарно: tmp + replace)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in cfg.items() if k in DEFAULTS})
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(SETTINGS_PATH)
