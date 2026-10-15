# -*- coding: utf-8 -*-
"""📣 Telegram — опция: пусто в настройках = тишина, всё и так на странице.

Три операции:
    send(...)      — отправить текст (HTML-разметка);
    find_chat(...) — найти chat_id: мама жмёт Start у бота, панель ловит;
    digest(...)    — красивая сводка новинок для мамы.
"""

from __future__ import annotations

import json
import urllib.request

API = "https://api.telegram.org/bot{token}/{method}"


def _call(token: str, method: str, payload: dict | None = None,
          timeout: int = 20) -> dict:
    """📡 Запрос к Bot API. Возвращает {"ok": bool, ...} (без исключений)."""
    url = API.format(token=token.strip(), method=method)
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 — наружу только понятный текст
        return {"ok": False, "description": f"{type(exc).__name__}: {exc}"}


def check(token: str) -> tuple[bool, str]:
    """✅ Проверить токен: имя бота при успехе."""
    if not token.strip():
        return False, "Токен пуст"
    res = _call(token, "getMe")
    if res.get("ok"):
        return True, f"Бот @{res['result'].get('username')} на связи"
    return False, str(res.get("description") or "не получилось")


def find_chat(token: str) -> tuple[bool, str, str]:
    """💬 Поймать chat_id: мама отправляет боту /start, панель ищет.

    Возвращает (ок, chat_id или "", понятное сообщение).
    """
    res = _call(token, "getUpdates", {"timeout": 0, "limit": 20})
    if not res.get("ok"):
        return False, "", str(res.get("description") or "нет связи")
    chats: list[tuple[int, str]] = []
    for upd in res.get("result") or []:
        msg = (upd.get("message") or upd.get("edited_message")
               or upd.get("channel_post") or {})
        chat = msg.get("chat") or {}
        if chat.get("id"):
            name = " ".join(x for x in (chat.get("first_name"),
                                        chat.get("last_name")) if x)
            chats.append((int(chat["id"]), name or str(chat["id"])))
    if not chats:
        return False, "", ("Никто ещё не написал боту. Попросите маму "
                           "нажать Start в Telegram — и нажмите снова.")
    chat_id, name = chats[-1]
    return True, str(chat_id), f"Найден чат: {name}"


def send(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """📨 Отправить сообщение (HTML, без превью ссылок)."""
    if not (token.strip() and str(chat_id).strip()):
        return False, "Не настроено (пусто)"
    res = _call(token, "sendMessage", {
        "chat_id": str(chat_id).strip(), "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": True})
    if res.get("ok"):
        return True, "отправлено"
    return False, str(res.get("description") or "не получилось")


def _esc(text: str) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def digest(items: list[dict], site_url: str = "", limit: int = 8) -> str:
    """🔔 Сводка «новые вакансии» одним сообщением (лимит — вежливость)."""
    lines = [f"🔔 <b>Новые вакансии: {len(items)}</b>", ""]
    for item in items[:limit]:
        title = _esc(item.get("title") or "Вакансия")
        price = _esc(item.get("price") or "з/п не указана")
        stars = ""
        rating = item.get("rating") or {}
        if rating.get("score"):
            stars = f" · ⭐{rating['score']} ({rating.get('reviews') or 0})"
        metro = f" · {_esc(item.get('metro'))}" if item.get("metro") else ""
        url = item.get("url") or ""
        link = f'<a href="{url}">{title}</a>' if url else title
        lines.append(f"• {link}\n   {price}{metro}{stars}")
    if len(items) > limit:
        lines.append(f"… и ещё {len(items) - limit}")
    if site_url:
        lines.append("")
        lines.append(f'🌐 Все вакансии: <a href="{site_url}">открыть '
                     f"страницу</a>")
    return "\n".join(lines)
