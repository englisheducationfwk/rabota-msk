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

import datetime
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

_MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5,
           "июня": 6, "июля": 7, "августа": 8, "сентября": 9, "октября": 10,
           "ноября": 11, "декабря": 12}


def parse_published(text: str) -> tuple[int, str]:
    """🗓️ Дата публикации со страницы вакансии → (unix-время, показ).

    Авито пишет по-разному: «сегодня в 17:02», «вчера в 9:40»,
    «12 октября в 14:05». Возвращаем метку времени и строку как есть —
    в карточке потом рядом и относительное («2 часа назад»), и точное.
    """
    plain = _clean(text)
    if not plain:
        return 0, ""
    now = datetime.datetime.now()
    m = re.search(r"(сегодня|вчера|\d{1,2}\s+[а-яё]+)\s+в\s+(\d{1,2}):(\d{2})",
                  plain)
    if not m:
        return 0, ""
    day_part, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
    try:
        if day_part == "сегодня":
            dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        elif day_part == "вчера":
            dt = (now - datetime.timedelta(days=1)).replace(
                hour=hh, minute=mm, second=0, microsecond=0)
        else:
            d = re.match(r"(\d{1,2})\s+([а-яё]+)", day_part)
            day = int(d.group(1))
            month = _MONTHS.get(d.group(2), 0)
            if not month:
                return 0, ""
            dt = datetime.datetime(now.year, month, day, hh, mm)
            if dt > now + datetime.timedelta(days=1):
                dt = dt.replace(year=now.year - 1)
    except ValueError:
        return 0, ""
    return int(dt.timestamp()), plain


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
    low = text.lower()
    if low.startswith("до "):
        out["to"] = nums[0]
    elif low.startswith("от "):
        out["from"] = nums[0]
        if len(nums) > 1:
            out["to"] = nums[1]
    else:
        out["from"] = nums[0]
        if len(nums) > 1:
            out["to"] = nums[1]
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
    base = out["to"] or out["from"]
    out["month"] = int(base * factor) if base else None
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
    """⭐ Найти рейтинг продавца: scoreFloat/score + число отзывов.

    Рейтинг Авито всегда 1.0–5.0; всё прочее — мусор из служебных данных
    страницы (метрики, скрипты) и выкидывается.
    """
    for keys in (("scoreFloat", "reviewsCount"),
                 ("scoreFloat", "activeReviewsCount"),
                 ("score", "reviewsCount")):
        hits: list[dict] = []

        def visit(node, keys=keys, hits=hits) -> None:
            if isinstance(node, dict) and keys[0] in node:
                score = node.get(keys[0])
                reviews = node.get(keys[1])
                if isinstance(score, (int, float)) and 1.0 <= score <= 5.0:
                    hits.append({"score": round(float(score), 1),
                                 "reviews": int(reviews or 0)})

        _walk(root, visit)
        if hits:
            return max(hits, key=lambda h: h["reviews"])
    return {}


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
        """🚀 Поднять браузер (профиль сохраняет куки между запусками).

        Флаги не дают Chrome «душить» отрисовку в свёрнутом/фоновом окне —
        без них JS-проверка Авито не успевает пройти и возвращается заслон.
        """
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
                  "--disable-background-timer-throttling",
                  "--disable-backgrounding-occluded-windows",
                  "--disable-renderer-backgrounding",
                  "--no-first-run", "--lang=ru-RU"],
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        if not self.headless:
            self._minimize()

    def _minimize(self) -> None:
        """🙈 Свернуть окно через CDP — чтобы не мешало за работой."""
        try:
            cdp = self.ctx.new_cdp_session(self.page)
            win = cdp.send("Browser.getWindowForTarget")
            cdp.send("Browser.setWindowBounds",
                     {"windowId": win["windowId"],
                      "bounds": {"windowState": "minimized"}})
        except Exception:
            pass

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
              timeout: int = 30000, wait_block_sec: int = 50) -> None:
        """📄 Открыть страницу; заслон по возможности отпускаем сами.

        «Проверка безопасности» обычно отпускает сама за 10–40 секунд,
        «проблема с IP» — ждём и жмём «Продолжить», сколько разрешено.
        """
        self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        deadline = time.time() + wait_block_sec
        clicked = 0
        while time.time() < deadline and self._blocked():
            if clicked < 4:
                try:
                    btn = self.page.query_selector(
                        "form.js-firewall-form button[name=submit]")
                    if btn and btn.is_visible():
                        btn.click()
                        clicked += 1
                except Exception:
                    pass
            self.page.wait_for_timeout(3000)
        if self._blocked():
            raise Firewall(
                "Авито показал «Доступ ограничен» (проверка IP). "
                "Запустите _tools/вход_в_авито.py и пройдите проверку.")
        if wait_selector:
            try:
                self.page.wait_for_selector(wait_selector,
                                            timeout=min(timeout, 20000))
            except Exception:
                pass  # возможно, выдача пустая — решаем по данным

    def _blocked(self) -> bool:
        """🚧 На странице сейчас заслон Авито?"""
        try:
            title = self.page.title()
        except Exception:
            return False
        if "Доступ ограничен" in title:
            return True
        try:
            body = self.page.inner_text("body")[:2500]
        except Exception:
            return False
        return "Доступ ограничен" in body

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

        items = self._dom_items(query)
        if not items:  # запасной путь — SSR-JSON
            hydra = self._hydration()
            if hydra:
                raws = find_item_dicts(hydra)
                items = [normalize_item(r, query) for r in raws]
        if items:
            self._save_sample("search", {"query": query, "page": page,
                                         "count": len(items),
                                         "first": items[0]})
        self.log(f"   🔎 «{query}» стр.{page}: {len(items)} карточек")
        return items

    def _dom_items(self, query: str) -> list[dict]:
        """🪵 Разбор выдачи из DOM (у Авито карточки в SSR-разметке).

        Проверенные селекторы (октябрь 2026): item-title, item-price,
        item-specific-params, item-location, seller-rating/score,
        seller-info/summary, badge-title-28.
        """
        try:
            rows = self.page.evaluate("""() => {
                const clean = (s) => (s || '').replace(/\\u00a0/g, ' ')
                    .replace(/\\s+/g, ' ').trim();
                const cards = document.querySelectorAll(
                    '[data-marker="item"][data-item-id]');
                return Array.from(cards).map(el => {
                    const pick = (sel) => {
                        const n = el.querySelector(sel);
                        return clean(n ? n.textContent : '');
                    };
                    const link = el.querySelector('a[itemprop="url"]')
                        || el.querySelector('a[data-marker="item-title"]');
                    const priceMeta = el.querySelector(
                        '[itemprop="price"]');
                    const ratingNode = el.querySelector(
                        '[data-marker="seller-rating/score"]');
                    const reviewsNode = el.querySelector(
                        '[data-marker="seller-info/summary"]');
                    const badges = Array.from(el.querySelectorAll(
                        '[data-marker^="badge-title"]'))
                        .map(b => clean(b.textContent));
                    const desc = (() => {
                        // превью описания — самый длинный <p> в карточке
                        let best = '';
                        el.querySelectorAll('p').forEach(p => {
                            const t = clean(p.textContent);
                            if (t.length > best.length) best = t;
                        });
                        return best;
                    })();
                    return {
                        id: el.getAttribute('data-item-id'),
                        title: pick('[data-marker="item-title"]'),
                        price: pick('[data-marker="item-price"]'),
                        priceValue: priceMeta
                            ? priceMeta.getAttribute('content') : '',
                        params: pick('[data-marker="item-specific-params"]'),
                        location: pick('[data-marker="item-location"]'),
                        href: link ? link.getAttribute('href') : '',
                        rating: pick('[data-marker="seller-rating/score"]'),
                        reviews: reviewsNode
                            ? clean(reviewsNode.textContent) : '',
                        badges: badges,
                        desc: desc,
                    };
                });
            }""")
        except Exception as exc:  # noqa: BLE001
            self.log(f"   ⚠️ DOM-разбор: {type(exc).__name__}")
            rows = []

        items: list[dict] = []
        for row in rows or []:
            raw = {
                "id": str(row.get("id") or ""),
                "title": row.get("title"),
                "urlPath": row.get("href") or "",
                "priceDetailed": {"string": row.get("price")},
                "address": row.get("location") or "",
            }
            item = normalize_item(raw, query)
            # перезаписи из точных полей карточки
            item["price_text"] = _clean(str(row.get("price") or ""))
            item["salary"] = parse_salary(item["price_text"])
            if row.get("desc"):
                item["description"] = _clean(str(row["desc"]))
            if row.get("priceValue"):
                try:
                    value = int(float(row["priceValue"]))
                    unit = item["salary"]["unit"]
                    factor = {"час": 160, "смена": 21, "сутки": 15,
                              "день": 22, "неделя": 4, "год": 1 / 12,
                              "месяц": 1}.get(unit, 1)
                    item["salary"]["month"] = int(value * factor)
                except (ValueError, TypeError):
                    pass
            item["address"] = _clean(str(row.get("location") or ""))
            item["metro"] = item["address"]
            item["params"] = [(_clean(p), "") for p in
                              str(row.get("params") or "").split("·")
                              if p.strip()]
            rating = str(row.get("rating") or "").replace(",", ".")
            reviews_text = str(row.get("reviews") or "")
            m = re.search(r"\d+", reviews_text.replace("\u00a0", " "))
            if rating:
                try:
                    item["rating"] = {
                        "score": float(rating),
                        "reviews": int(m.group(0)) if m else 0,
                    }
                except ValueError:
                    pass
            item["badges"] = [b for b in (row.get("badges") or [])
                              if b][:6]
            items.append(item)
        return items

    def details(self, url: str) -> dict:
        """📇 Детали вакансии: описание, условия, работодатель, рейтинг.

        Маркеры проверены на живой странице (октябрь 2026):
        item-view/item-description, item-view/item-params, seller-info/name.
        """
        self._goto(url, wait_selector='[data-marker="item-view/item-title'
                                      '-info"], [data-marker="item-view/'
                                      'item-description"]')
        polite_sleep(0.6, 1.2)
        out = {"description": "", "params": [], "rating": {},
               "title": "", "employer": ""}

        def pick(selector: str) -> str:
            try:
                node = self.page.query_selector(selector)
                return _clean(node.inner_text()) if node else ""
            except Exception:
                return ""

        out["description"] = pick('[data-marker="item-view/item-description"]')
        employer = pick('[data-marker="seller-info/name"]')
        # «Работа Всем Работодатель На Авито c 2024 года» → «Работа Всем»
        employer = re.split(r"\bРаботодатель\b|\bНа Авито\b", employer)[0]
        out["employer"] = _clean(employer)
        out["title"] = pick('[data-marker="item-view/title-info"]')

        # дата публикации: « · сегодня в 17:02 · 3 просмотра …»
        date_text = pick('[data-marker="item-view/item-date"]')
        published_ts, published_text = parse_published(date_text)
        out["published_ts"] = published_ts
        out["published_text"] = published_text

        params_text = pick('[data-marker="item-view/item-params"]')
        if params_text:
            # «График: Гибкий Занятость: Постоянная Способ оформления: …»
            parts = re.split(r"(?<=[а-яё0-9\)])\s+(?=[А-ЯЁ][^:]{2,60}:)",
                             params_text)
            for part in parts:
                name, _, value = part.partition(":")
                pair = (_clean(name), _clean(value))
                if pair[0] and pair[1] and len(pair[0]) <= 60:
                    out["params"].append(pair)

        # рейтинг: в гидратации страницы (scoreFloat/reviewsCount)
        hydra = self._hydration()
        if hydra:
            out["rating"] = find_rating(hydra)
        return out

    def employer(self, seller_id: str) -> dict:
        """👤 Профиль работодателя: имя + рейтинг/отзывы (кэш — в БД)."""
        if not seller_id:
            return {}
        self._goto(f"{BASE}/brands/{seller_id}")  # откроется профиль или 404
        hydra = self._hydration()
        return find_rating(hydra) if hydra else {}
