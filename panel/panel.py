# -*- coding: utf-8 -*-
"""🎛️ Панель «Работа MSK» — то самое окно с кнопками.

Открыл ярлык на рабочем столе → видишь:
    ▶ Включить сервер   — запускает сбор (Авито → мозг → база → GitHub);
    ⏹ Выключить сервер  — останавливает всё;
    рядом: войти в Авито, открыть страницу мамы, опубликовать сейчас,
    настройки (запросы, интервал, Telegram) и журнал простыми словами.

Панель — лицо проекта: сама ничего не собирает, а следит за процессом
сбора (collect.py) и показывает его статус из data/status.json.
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collector import notify, settings, store  # noqa: E402

BG = "#12141c"
CARD = "#1b1e2a"
FG = "#e8eaf2"
MUTED = "#8b90a5"
GREEN = "#2e9e63"
RED = "#c0392b"
BLUE = "#3b6fd4"
AMBER = "#c98a1b"
FONT = ("Segoe UI", 11)
FONT_BIG = ("Segoe UI", 15, "bold")
FONT_TITLE = ("Segoe UI", 14, "bold")

STATES = {
    "ok": ("🟢", GREEN),
    "idle": ("🟡", AMBER),
    "firewall": ("🟠", AMBER),
    "tunnel": ("🔴", RED),
    "error": ("🔴", RED),
}


class Panel(tk.Tk):
    """🎛️ Главное окно."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Работа MSK — сбор вакансий с Авито")
        self.configure(bg=BG)
        self.geometry("760x560")
        self.minsize(680, 480)

        self.proc: subprocess.Popen | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.cfg = settings.load()
        self.preview_server = None

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(300, self._pump_log)
        self.after(400, self._tick_status)

    # --- сборка окна -------------------------------------------------------
    def _build(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG, font=FONT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED,
                        font=("Segoe UI", 10))
        style.configure("Big.TButton", font=FONT_BIG, padding=(18, 12))
        style.configure("TButton", font=FONT, padding=(10, 6))

        top = ttk.Frame(self, padding=(16, 14, 16, 6))
        top.pack(fill="x")
        ttk.Label(top, text="🧹 Работа MSK", font=FONT_TITLE).pack(side="left")
        self.lbl_ip = ttk.Label(top, text="", style="Muted.TLabel")
        self.lbl_ip.pack(side="right")

        body = ttk.Frame(self, padding=(16, 4, 16, 8))
        body.pack(fill="x")

        self.btn_toggle = ttk.Button(body, text="▶  Включить сервер",
                                     style="Big.TButton",
                                     command=self._toggle)
        self.btn_toggle.pack(side="left")
        ttk.Button(body, text="🔑 Войти в Авито",
                   command=self._login_avito).pack(side="left", padx=(10, 0))
        ttk.Button(body, text="🌐 Открыть страницу",
                   command=self._open_site).pack(side="left", padx=(10, 0))
        ttk.Button(body, text="👁 Посмотреть у себя",
                   command=self._preview).pack(side="left", padx=(10, 0))

        status = ttk.Frame(self, padding=(16, 6, 16, 4))
        status.pack(fill="x")
        self.lbl_state = ttk.Label(status, text="⚪ Сбор выключен",
                                   font=("Segoe UI", 12, "bold"))
        self.lbl_state.pack(anchor="w")
        self.lbl_detail = ttk.Label(status, text="", style="Muted.TLabel")
        self.lbl_detail.pack(anchor="w", pady=(2, 0))

        row2 = ttk.Frame(self, padding=(16, 6, 16, 6))
        row2.pack(fill="x")
        ttk.Button(row2, text="⬆️ Опубликовать сейчас",
                   command=self._publish_now).pack(side="left")
        ttk.Button(row2, text="⚙️ Настройки",
                   command=self._open_settings).pack(side="left", padx=(10, 0))
        ttk.Button(row2, text="🗑 Очистить журнал",
                   command=self._clear_log).pack(side="left", padx=(10, 0))

        log_frame = ttk.Frame(self, padding=(16, 4, 16, 14))
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, bg="#0c0e15", fg="#cfd4e4",
                           font=("Consolas", 10), wrap="word",
                           relief="flat", padx=10, pady=8, state="disabled")
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)
        self._log("Панель готова. Нажмите «Включить сервер».")

    # --- кнопки -------------------------------------------------------------
    def _toggle(self) -> None:
        if self.proc and self.proc.poll() is None:
            self._stop_server()
        else:
            self._start_server()

    def _start_server(self) -> None:
        if not (self.cfg.get("repo_url") or "").strip():
            self._log("⚠️ В настройках не задан адрес GitHub-репозитория — "
                      "сбор пойдёт, но публикации не будет.")
        self.cfg = settings.load()
        env = {**__import__("os").environ,
               "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        self.proc = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "collector" / "collect.py")],
            cwd=str(ROOT), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._reader, daemon=True).start()
        self.btn_toggle.configure(text="⏹  Выключить сервер")
        self._set_state("idle", "🟡 Сбор запускается…", "")

    def _stop_server(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                subprocess.run(["taskkill", "/PID", str(self.proc.pid),
                                "/T", "/F"], capture_output=True,
                               creationflags=getattr(subprocess,
                                                     "CREATE_NO_WINDOW", 0))
            except Exception:
                self.proc.kill()
        self.proc = None
        self.btn_toggle.configure(text="▶  Включить сервер")
        self._set_state("idle", "⚪ Сбор выключен", "")
        self._log("⏹ Сбор остановлен.")

    def _reader(self) -> None:
        """📖 Читает stdout сбора и перекладывает в очередь для окна."""
        proc = self.proc
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            self.log_queue.put(line.rstrip())
        self.log_queue.put("__PROC_END__")

    def _login_avito(self) -> None:
        env = {**__import__("os").environ, "PYTHONUTF8": "1"}
        subprocess.Popen(
            [sys.executable,
             str(ROOT / "_tools" / "вход_в_авито.py")],
            cwd=str(ROOT), env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._log("🔑 Открываю окно входа в Авито: нажмите «Продолжить» "
                  "и пройдите проверку — окно закроется само.")

    def _open_site(self) -> None:
        url = (self.cfg.get("site_url") or "").strip()
        if url:
            webbrowser.open(url)
            self._log(f"🌐 Открываю страницу: {url}")
        else:
            messagebox.showinfo(
                "Страница", "Пока не задан адрес страницы.\n"
                "Он появится в настройках, когда опубликуем проект "
                "на GitHub Pages.\n\nМожно посмотреть локально кнопкой "
                "«Посмотреть у себя».")

    def _preview(self) -> None:
        """👁 Локальный предпросмотр страницы мамы (без GitHub)."""
        try:
            store.export_site(store.connect(), store.new_since(store.connect()))
        except Exception:
            pass
        src = store.EXPORT_PATH
        dst_dir = ROOT / "docs" / "data"
        dst_dir.mkdir(parents=True, exist_ok=True)
        try:
            if src.exists():
                (dst_dir / "vacancies.json").write_text(
                    src.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self._log(f"⚠️ Не скопировался снимок данных: {exc}")
        if self.preview_server is None:
            threading.Thread(target=self._serve_docs, daemon=True).start()
            time.sleep(0.4)
        webbrowser.open("http://127.0.0.1:8788/index.html")
        self._log("👁 Открыл предпросмотр: http://127.0.0.1:8788/index.html")

    @staticmethod
    def _serve_docs() -> None:
        import http.server
        import functools
        handler = functools.partial(
            http.server.SimpleHTTPRequestHandler,
            directory=str(ROOT / "docs"))
        with http.server.ThreadingHTTPServer(("127.0.0.1", 8788),
                                             handler) as srv:
            srv.serve_forever()

    def _publish_now(self) -> None:
        self.cfg = settings.load()
        if not (self.cfg.get("repo_url") or "").strip():
            messagebox.showwarning("Публикация",
                                   "Сначала укажите адрес GitHub-репозитория "
                                   "в настройках.")
            return
        self._log("⬆️ Публикую данные на GitHub…")
        threading.Thread(target=self._publish_worker, daemon=True).start()

    def _publish_worker(self) -> None:
        from collector import publish
        try:
            con = store.connect()
            payload = store.export_site(con, store.new_since(con))
            con.close()
            ok, info = publish.publish(
                self.cfg["repo_url"], self.cfg.get("repo_branch") or "data",
                payload)
            self.log_queue.put(f"{'✅' if ok else '⚠️'} Публикация: {info}")
        except Exception as exc:  # noqa: BLE001
            self.log_queue.put(f"⚠️ Публикация не удалась: "
                               f"{type(exc).__name__}: {exc}")

    # --- настройки ----------------------------------------------------------
    def _open_settings(self) -> None:
        win = tk.Toplevel(self)
        win.title("Настройки")
        win.configure(bg=BG)
        win.geometry("640x620")
        win.transient(self)

        cfg = settings.load()
        rows = [
            ("Запросы к Авито (по одному в строке)", "queries", "text"),
            ("Интервал автосбора, минут", "interval_min", "int"),
            ("Минимальная зарплата ₽/мес (0 — все)", "min_salary_month",
             "int"),
            ("Telegram-токен (опция)", "telegram_token", "str"),
            ("Telegram chat_id мамы", "telegram_chat", "str"),
            ("Адрес GitHub-репозитория", "repo_url", "str"),
            ("Ветка данных", "repo_branch", "str"),
            ("Адрес страницы (GitHub Pages)", "site_url", "str"),
        ]
        widgets: dict[str, tk.Widget] = {}

        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)
        for idx, (label, key, kind) in enumerate(rows):
            ttk.Label(frame, text=label).grid(row=idx, column=0, sticky="nw",
                                              pady=(6, 0))
            if kind == "text":
                box = tk.Text(frame, height=6, width=48, bg="#0c0e15",
                              fg="#cfd4e4", insertbackground="#cfd4e4",
                              relief="flat", font=("Segoe UI", 10))
                box.insert("1.0", "\n".join(cfg.get(key) or []))
                box.grid(row=idx, column=1, sticky="we", pady=(6, 0))
                widgets[key] = box
            else:
                var = tk.StringVar(value=str(cfg.get(key) or ""))
                ent = ttk.Entry(frame, textvariable=var, width=48)
                ent.grid(row=idx, column=1, sticky="we", pady=(6, 0))
                widgets[key] = var
        frame.columnconfigure(1, weight=1)

        tg = ttk.Frame(frame)
        tg.grid(row=len(rows), column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Button(tg, text="Проверить бота",
                   command=self._tg_check).pack(side="left")
        ttk.Button(tg, text="Привязать маму",
                   command=lambda: self._tg_bind(widgets)
                   ).pack(side="left", padx=(8, 0))
        ttk.Button(tg, text="Отправить тест",
                   command=lambda: self._tg_test(widgets)
                   ).pack(side="left", padx=(8, 0))

        def save_and_close() -> None:
            new = dict(cfg)
            new["queries"] = [q.strip() for q in
                              widgets["queries"].get("1.0", "end").splitlines()
                              if q.strip()]
            for key in ("interval_min", "min_salary_month"):
                try:
                    new[key] = max(0, int(widgets[key].get()))
                except (ValueError, tk.TclError):
                    pass
            new["interval_min"] = max(5, int(new.get("interval_min") or 15))
            for key in ("telegram_token", "telegram_chat", "repo_url",
                        "repo_branch", "site_url"):
                new[key] = widgets[key].get().strip()
            settings.save(new)
            self.cfg = new
            self._log("⚙️ Настройки сохранены.")
            win.destroy()

        ttk.Button(frame, text="💾 Сохранить",
                   command=save_and_close).grid(row=len(rows) + 1, column=0,
                                                columnspan=2, pady=(16, 0))

    def _tg_values(self, widgets) -> tuple[str, str]:
        token = widgets["telegram_token"].get().strip()
        chat = widgets["telegram_chat"].get().strip()
        return token, chat

    def _tg_check(self) -> None:
        """✅ Кнопка «Проверить бота»: берём токен прямо из настроек."""
        ok, msg = notify.check(settings.load().get("telegram_token", ""))
        messagebox.showinfo("Telegram", msg)

    def _tg_bind(self, widgets) -> None:
        token, _ = self._tg_values(widgets)
        ok, chat, msg = notify.find_chat(token)
        if ok:
            widgets["telegram_chat"].set(chat)
        messagebox.showinfo("Telegram", msg)

    def _tg_test(self, widgets) -> None:
        token, chat = self._tg_values(widgets)
        ok, msg = notify.send(token, chat,
                              "🔔 Это тест от «Работа MSK». "
                              "Уведомления настроены!")
        messagebox.showinfo("Telegram", msg)

    # --- статус и журнал ------------------------------------------------------
    def _tick_status(self) -> None:
        self.cfg = settings.load()
        running = bool(self.proc and self.proc.poll() is None)
        try:
            if store.STATUS_PATH.exists():
                st = json.loads(store.STATUS_PATH.read_text(encoding="utf-8"))
                key = st.get("state") or "idle"
                icon, color = STATES.get(key, ("⚪", MUTED))
                if key == "ok":
                    last = time.strftime("%H:%M",
                                         time.localtime(st.get("last_run") or 0))
                    nxt = time.strftime(
                        "%H:%M", time.localtime(st.get("next_run") or 0))
                    text = (f"🟢 Сбор работает · Обновлено {last} · "
                            f"Следующее ~{nxt} · Новых: {st.get('fresh', 0)}")
                    self._set_state("ok", text,
                                    st.get("message") or "", color)
                elif key == "firewall":
                    self._set_state("firewall",
                                    "🟠 Авито просит проверку — нажмите "
                                    "«Войти в Авито»", st.get("message") or "",
                                    color)
                elif key == "tunnel":
                    self._set_state("tunnel", "🔴 Трафик идёт через туннель",
                                    st.get("message") or "", color)
                elif key == "error":
                    self._set_state("error", "🔴 Ошибка сбора",
                                    st.get("message") or "", color)
                elif not running:
                    self._set_state("idle", "⚪ Сбор выключен",
                                    st.get("message") or "")
                self.lbl_ip.configure(text=st.get("ip") or "")
                detail = []
                if st.get("publish"):
                    detail.append(f"GitHub: {st['publish']}")
                if st.get("telegram"):
                    detail.append(f"Telegram: {st['telegram']}")
                if detail:
                    self.lbl_detail.configure(text=" · ".join(detail))
        except Exception:
            pass
        if running:
            self.btn_toggle.configure(text="⏹  Выключить сервер")
        else:
            self.btn_toggle.configure(text="▶  Включить сервер")
        self.after(2000, self._tick_status)

    def _set_state(self, key: str, text: str, detail: str,
                   color: str | None = None) -> None:
        self.lbl_state.configure(text=text)
        if color:
            self.lbl_state.configure(foreground=color)
        if detail:
            self.lbl_detail.configure(text=detail)

    def _pump_log(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line == "__PROC_END__":
                    self._log("⏹ Процесс сбора завершился.")
                    continue
                self._log(line)
        except queue.Empty:
            pass
        self.after(300, self._pump_log)

    def _log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _on_close(self) -> None:
        self._stop_server()
        self.destroy()


def main() -> None:
    Panel().mainloop()


if __name__ == "__main__":
    main()
