# -*- coding: utf-8 -*-
"""🔎 Авито: поиск вакансий и детали — живым браузером по РУ-каналу.

Ходим как обычный посетитель: тот же браузерный профиль, что прошёл
первую проверку (`_tools/вход_в_авито.py`), те же куки. Трафик — через
локальный мостик (bind к Wi-Fi), то есть напрямую, с российского IP.

Данные берём из того, что страница отдаёт сама: в HTML вшит SSR-JSON
(`__staticRouterHydrationData`) — оттуда карточки надёжнее, чем из DOM.
Если JSON нет — падаем на DOM-разбор по `data-marker`.

Вежливость: паузы 3–6 сек между запросами, 1 поток, детали — только
для новых вакансий. Если Авито показал «Доступ ограничен» — Firewall.
"""

from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from urllib.parse import quote

BRIDGE_PORT = 8790
BASE = "https://www.avito.ru"

# «Работа» — раздел каталога Авито (categoryId=110) и Москва.
REGION_URL = "moskva/rabota"
SORT_DATE = "s=104"


class Firewall(Exception):
    """Авито показал заслон: «Доступ ограничен: проблема с IP» + капча."""


def polite_sleep(lo: float = 3.0, hi: float = 6.0) -> None:
    """🐢 Пауза, как у живого человека, а не как у робота."""
    time.sleep(random.uniform(lo, hi))


def _clean(text: str) -> str:
    """Пробелы/юникод к нормальному виду (у Авито неразрывные всюду)."""
    return re.sub(r"\s+", " ", (text or "").replace("\u00a0", " ")).strip()


def parse_salary(price_text: str) -> dict:
    """💰 «4 000 – 5 500 ₽ за смену» → числа, единица, оценка в месяц.

    Оценка «≈ в месяц» нужна только для честного сравнения вакансий
    между собой (сортировка «выгода»); в карточке она помечена «≈».
    """
    text = _clean(price_text)
    out = {"text": text, "from": None, "to": None, "unit": "месяц",
           "month": None}
    if not text:
        return out
    nums = [int(n.replace(" ", "")) for n in
            re.findall(r"\d[\d\s]*", text) if n.strip()]
    if not nums:
        return out
    out["from"] = nums[0]
    if len(nums) > 1:
        out["to"] = nums[1]
    low = text.lower()
    unit = "месяц"
    factor = 1
    if "час" in low:
        unit, factor = "час", 160
    elif "смен" in low:
        unit, factor = "смена", 21
    elif "сутк" in low:
        unit, factor = "сутки", 15
    elif "день" in low or "дня" in low:
        unit, factor = "день", 22
    elif "недел" in low:
        unit, factor = "неделя", 4
    elif "год" in low:
        unit, factor = "год", 1 / 12
    out["unit"] = unit
    out["month"] = int((out["to"] or out["from"]) * factor)
    return out


# --- разбор SSR-JSON --------------------------------------------------------

def _walk(obj, visit, depth: int = 0) -> None:
    """🌳 Обойти дерево JSON, вызывая visit на каждом узле (с защитой)."""
    if depth > 40:
        return
    visit(obj)
    if isinstance(obj, dict):
        for value in obj.values():
            _walk(value, visit, depth + 1)
    elif isinstance(obj, list):
        for value in obj:
            _walk(value, visit, depth + 1)


def find_item_dicts(root, limit: int = 300) -> list[dict]:
    """🎯 Найти «карточки вакансий» в SSR-JSON по приметам, а не по пути.

    Путь меняется у Авито от релиза к релизу, а набор полей карточки —
    нет: id + title + цена. Поэтому ищем по признакам и не привязываемся
    к конкретной ветке дерева.
    """
    found: list[dict] = []
    ids: set[str] = set()

    def visit(node) -> None:
        if len(found) >= limit or not isinstance(node, dict):
            return
        if ("title" in node and "id" in node
                and ("priceDetailed" in node or "price" in node)):
            key = str(node.get("id"))
            if key not in ids and node.get("urlPath"):
                ids.add(key)
                found.append(node)

    _walk(root, visit)
    return found


def find_rating(root) -> dict:
    """⭐ Найти рейтинг продавца: scoreFloat/score + число отзывов."""
    best: dict = {}
    for keys in (("scoreFloat", "reviewsCount"),
                 ("score", "reviewsCount"),
                 ("scoreFloat", "activeReviewsCount")):
        hits: list[dict] = []

        def visit(node, keys=keys, hits=hits) -> None:
            if isinstance(node, dict) and keys[0] in node:
                score = node.get(keys[0])
                reviews = node.get(keys[1])
                if isinstance(score, (int, float)):
                    hits.append({"score": round(float(score), 1),
                                 "reviews": int(reviews or 0)})

        _walk(root, visit)
        if hits:
            best = max(hits, key=lambda h: h["reviews"])
            return best
    return best


def find_description(root) -> str:
    """📝 Самое длинное поле description в дереве — это текст вакансии."""
    best = ""

    def visit(node) -> None:
        nonlocal best
        if isinstance(node, dict):
            for key in ("description", "descriptionHtml"):
                value = node.get(key)
                if isinstance(value, str) and len(value) > len(best):
                    best = value

    _walk(root, visit)
    best = re.sub(r"<br\s*/?>", "\n", best)
    best = re.sub(r"<[^>]+>", "", best)
    return best.strip()


def find_params(root) -> list[tuple[str, str]]:
    """🧾 Параметры вакансии (оформление, график, опыт) — список пар."""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def visit(node) -> None:
        if isinstance(node, dict):
            name = node.get("name") or node.get("title")
            value = node.get("value")
            if (isinstance(name, str) and isinstance(value, str)
                    and 1 < len(name) < 40 and len(value) < 80):
                pair = (_clean(name), _clean(value))
                if pair not in seen:
                    seen.add(pair)
                    out.append(pair)

    _walk(root, visit)
    return out[:40]


def normalize_item(raw: dict, query: str) -> dict:
    """🧱 Карточка выдачи → наша схема (всё, что нужно мозгу и странице)."""
    price_text = ""
    for path in (("priceDetailed", "string"), ("priceDetailed", "fullString")):
        node = raw
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, str) and node:
            price_text = node
            break
    if not price_text and isinstance(raw.get("price"), str):
        price_text = raw["price"]

    title = _clean(str(raw.get("title") or ""))
    url_path = raw.get("urlPath") or ""
    url = url_path if url_path.startswith("http") else BASE + url_path

    address = ""
    geo = raw.get("geo") or raw.get("location") or {}
    if isinstance(geo, dict):
        address = _clean(str(geo.get("name") or geo.get("address") or ""))
    metro = ""
    refs = geo.get("geoReferences") if isinstance(geo, dict) else None
    if isinstance(refs, list):
        parts = [_clean(str(r.get("content") or r.get("name") or ""))
                 for r in refs if isinstance(r, dict)]
        parts = [p for p in parts if p]
        metro = ", ".join(parts[:2])
    if not address:
        address = _clean(str(raw.get("address") or ""))

    seller = raw.get("seller") if isinstance(raw.get("seller"), dict) else {}
    item = {
        "id": str(raw.get("id")),
        "query": query,
        "title": title,
        "url": url,
        "price_text": _clean(price_text),
        "salary": parse_salary(price_text),
        "employer": _clean(str(seller.get("name") or
                               raw.get("sellerName") or "")),
        "employer_id": str(raw.get("sellerId") or seller.get("id") or ""),
        "metro": metro,
        "address": address,
        "published_ts": int(raw.get("sortTimeStamp") or
                            raw.get("time") or 0),
        "description": _clean(str(raw.get("description") or
                                  raw.get("descriptionPreview") or "")),
        "badges": _collect_badges(raw),
        "category_id": str(raw.get("categoryId") or ""),
        "params": [],
        "rating": {},
    }
    return item


def _collect_badges(raw: dict) -> list[str]:
    """🏷️ Бейджи карточки («Резюме», «Услуга», «Новое»…) — из iva/absolute."""
    out: list[str] = []
    node = raw.get("iva")
    if isinstance(node, dict):
        for key in node.keys():
            if key and len(str(key)) < 40:
                out.append(_clean(str(key)))
    return out


# --- живой браузер ----------------------------------------------------------

class AvitoBrowser:
    """🌐 Сессия Авито: persistent-профиль + мостик к РУ-каналу."""

    def __init__(self, profile_dir: Path, log=print, headless: bool = True,
                 bridge_port: int = BRIDGE_PORT, samples_dir: Path | None = None):
        self.profile = str(profile_dir)
        self.log = log
        self.headless = headless
        self.bridge_port = bridge_port
        self.samples_dir = samples_dir
        self._pw = None
        self.ctx = None
        self.page = None

    # -- управление --
    def start(self) -> None:
        """🚀 Поднять браузер (профиль сохраняет куки между запусками)."""
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.launch_persistent_context(
            self.profile,
            headless=self.headless,
            viewport={"width": 1280, "height": 900},
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            proxy={"server": f"http://127.0.0.1:{self.bridge_port}"},
            args=["--disable-blink-features=AutomationControlled",
                  "--no-first-run", "--lang=ru-RU"],
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()

    def stop(self) -> None:
        """🛑 Погасить браузер и playwright (без исключений наружу)."""
        for closer in (getattr(self.ctx, "close", None),
                       getattr(self._pw, "stop", None)):
            try:
                if closer:
                    closer()
            except Exception:
                pass
        self.ctx = None
        self._pw = None

    def __enter__(self) -> "AvitoBrowser":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- сеть --
    def _goto(self, url: str, wait_selector: str | None = None,
              timeout: int = 30000) -> None:
        """📄 Открыть страницу и убедиться, что это не заслон."""
        self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        try:
            body = self.page.inner_text("body")[:4000]
        except Exception:
            body = ""
        title = ""
        try:
            title = self.page.title()
        except Exception:
            pass
        if "Доступ ограничен" in title or "Доступ ограничен" in body:
            raise Firewall(
                "Авито показал «Доступ ограничен» (проверка IP). "
                "Запустите _tools/вход_в_авито.py и пройдите проверку.")
        if wait_selector:
            try:
                self.page.wait_for_selector(wait_selector, timeout=timeout)
            except Exception:
                pass  # возможно, выдача пустая — решаем по данным

    def _hydration(self):
        """🧩 SSR-JSON страницы (или None) — главный источник данных."""
        try:
            raw = self.page.evaluate(
                "() => { try { const d = window.__staticRouterHydrationData;"
                " return d ? JSON.stringify(d) : null } catch(e){ return null } }")
        except Exception:
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def _save_sample(self, name: str, payload) -> None:
        """💾 Сохранить образец страницы — по нему отлаживаем разбор."""
        if not self.samples_dir:
            return
        try:
            self.samples_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            path = self.samples_dir / f"{name}_{stamp}.json"
            with path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
        except Exception:
            pass

    # -- поиск и детали --
    def search(self, query: str, page: int = 1) -> list[dict]:
        """🔎 Выдача по запросу (Москва, раздел «Работа», свежие сверху)."""
        url = (f"{BASE}/{REGION_URL}?q={quote(query)}&{SORT_DATE}"
               + (f"&p={page}" if page > 1 else ""))
        self._goto(url, wait_selector='[data-marker="item"]')
        polite_sleep(0.6, 1.2)

        hydra = self._hydration()
        items: list[dict] = []
        if hydra:
            raws = find_item_dicts(hydra)
            items = [normalize_item(r, query) for r in raws]
            if items:
                self._save_sample("search", {"query": query, "page": page,
                                             "count": len(items),
                                             "first": items[0]})
        if not items:  # запасной путь — DOM
            items = self._dom_items(query)
        self.log(f"   🔎 «{query}» стр.{page}: {len(items)} карточек")
        return items

    def _dom_items(self, query: str) -> list[dict]:
        """🪵 Запасной разбор: атрибуты data-marker, если JSON не нашёлся."""
        try:
            rows = self.page.evaluate("""() => Array.from(
                document.querySelectorAll('[data-marker="item"]')).map(el => {
                const t = el.querySelector('[itemprop="name"], [data-marker="item-title"]');
                const p = el.querySelector('[itemprop="price"], [data-marker="item-price"]');
                const a = el.querySelector('a[itemprop="url"], a[data-marker="item-title"]');
                const addr = el.querySelector('[data-marker="item-address"]');
                return {title: t ? t.textContent : '',
                        price: p ? p.textContent : '',
                        href: a ? a.href : '',
                        address: addr ? addr.textContent : ''};
            })""")
        except Exception:
            rows = []
        out: list[dict] = []
        for i, row in enumerate(rows or []):
            href = str(row.get("href") or "")
            m = re.search(r"_(\d+)(?:\?|$)", href)
            item_id = m.group(1) if m else f"dom_{i}"
            item = normalize_item(
                {"id": item_id, "title": row.get("title"),
                 "priceDetailed": {"string": row.get("price")},
                 "urlPath": href.replace(BASE, ""),
                 "address": row.get("address")}, query)
            out.append(item)
        return out

    def details(self, url: str) -> dict:
        """📇 Детали вакансии: описание, параметры, рейтинг работодателя."""
        self._goto(url, wait_selector='[data-marker="item-view"]')
        polite_sleep(0.6, 1.2)
        hydra = self._hydration()
        out = {"description": "", "params": [], "rating": {},
               "title": "", "employer": ""}
        if hydra:
            out["description"] = find_description(hydra)
            out["params"] = find_params(hydra)
            out["rating"] = find_rating(hydra)
            raws = find_item_dicts(hydra, limit=5)
            if raws:
                card = normalize_item(raws[0], "")
                out["title"] = card["title"]
                out["employer"] = card["employer"] or ""
                if not out["rating"]:
                    out["rating"] = {}
        if not out["description"]:
            try:
                node = self.page.query_selector(
                    '[data-marker="item-view/itemDescription"]')
                if node:
                    out["description"] = node.inner_text().strip()
            except Exception:
                pass
        return out

    def employer(self, seller_id: str) -> dict:
        """👤 Профиль работодателя: имя + рейтинг/отзывы (кэш — в БД)."""
        if not seller_id:
            return {}
        self._goto(f"{BASE}/brands/{seller_id}")  # откроется профиль или 404
        hydra = self._hydration()
        return find_rating(hydra) if hydra else {}
