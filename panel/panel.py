# -*- coding: utf-8 -*-
"""🎛️ Панель «Работа MSK» — окно с кнопками + жизнь в трее.

Как устроено:
    · ярлык на рабочем столе → открывает это окно;
    · окно можно свернуть в трей (крестик прячет, а не закрывает);
    · в трее иконка с меню: открыть панель / вкл-выкл сбора / выход;
    · автозапуск: папка «Автозагрузка» Windows (ставится кнопкой в
      настройках) — после перезагрузки ПК сервер поднимается сам;
    · при включении сбор идёт сразу и дальше каждые 15 минут.

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
AMBER = "#c98a1b"
FONT = ("Segoe UI", 11)
FONT_BIG = ("Segoe UI", 14, "bold")
FONT_TITLE = ("Segoe UI", 14, "bold")

STATES = {
    "ok": ("🟢", GREEN),
    "idle": ("🟡", AMBER),
    "firewall": ("🟠", AMBER),
    "tunnel": ("🔴", RED),
    "error": ("🔴", RED),
}

AUTOSTART_DIR = (Path.home() / "AppData" / "Roaming" / "Microsoft" /
                 "Windows" / "Start Menu" / "Programs" / "Startup")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "RabotaMSK"


class Panel(tk.Tk):
    """🎛️ Главное окно + трей."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Работа MSK — сбор вакансий с Авито")
        self.configure(bg=BG)
        self.geometry("780x580")
        self.minsize(700, 500)

        self.proc: subprocess.Popen | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.cfg = settings.load()
        self.preview_server = None
        self.tray = None
        self._quitting = False
        self._was_running = False
        self._last_start = 0.0

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self.after(300, self._pump_log)
        self.after(400, self._tick_status)
        self._refresh_mode_ui()
        self._start_tray()
        if self.cfg.get("auto_start", True):
            self.after(1200, self._maybe_autostart)

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
        ttk.Label(top, text="💼 Работа MSK", font=FONT_TITLE).pack(side="left")
        ttk.Button(top, text="В трей", command=self._hide_to_tray) \
            .pack(side="right")
        self.lbl_ip = ttk.Label(top, text="", style="Muted.TLabel")
        self.lbl_ip.pack(side="right", padx=(0, 12))

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

        mode_row = ttk.Frame(self, padding=(16, 6, 16, 0))
        mode_row.pack(fill="x")
        ttk.Label(mode_row, text="Режим сбора:").pack(side="left")
        self.btn_mode_daily = ttk.Button(
            mode_row, text="🕐 2 раза в день",
            command=lambda: self._set_mode("daily"))
        self.btn_mode_daily.pack(side="left", padx=(8, 0))
        self.btn_mode_freq = ttk.Button(
            mode_row, text="⚡ каждые 15 минут",
            command=lambda: self._set_mode("frequent"))
        self.btn_mode_freq.pack(side="left", padx=(6, 0))
        self.lbl_mode = ttk.Label(mode_row, text="", style="Muted.TLabel")
        self.lbl_mode.pack(side="left", padx=(10, 0))

        status = ttk.Frame(self, padding=(16, 6, 16, 4))
        status.pack(fill="x")
        self.lbl_state = ttk.Label(status, text="⚪ Сбор выключен",
                                   font=("Segoe UI", 12, "bold"))
        self.lbl_state.pack(anchor="w")
        self.lbl_detail = ttk.Label(status, text="", style="Muted.TLabel")
        self.lbl_detail.pack(anchor="w", pady=(2, 0))
        self.lbl_hint = ttk.Label(
            status, text="Окно можно закрыть — сбор продолжит работать "
                         "в трее (иконка 💼 рядом с часами).",
            style="Muted.TLabel")
        self.lbl_hint.pack(anchor="w", pady=(2, 0))

        row2 = ttk.Frame(self, padding=(16, 6, 16, 6))
        row2.pack(fill="x")
        ttk.Button(row2, text="⬆️ Опубликовать сейчас",
                   command=self._publish_now).pack(side="left")
        ttk.Button(row2, text="⚙️ Настройки",
                   command=self._open_settings).pack(side="left", padx=(10, 0))
        ttk.Button(row2, text="🗑 Очистить журнал",
                   command=self._clear_log).pack(side="left", padx=(10, 0))
        ttk.Button(row2, text="✖ Выйти совсем",
                   command=self._quit).pack(side="right")

        log_frame = ttk.Frame(self, padding=(16, 4, 16, 14))
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, bg="#0c0e15", fg="#cfd4e4",
                           font=("Consolas", 10), wrap="word",
                           relief="flat", padx=10, pady=8, state="disabled")
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)
        self._log("Панель готова. «Включить сервер» — и вакансии поехали.")

    # --- трей ---------------------------------------------------------------
    def _tray_image(self):
        """🚩 Иконка для трея из наших PNG (msk.ico не читает pystray)."""
        try:
            from PIL import Image
            for name in ("icon-192.png", "apple-touch-icon.png"):
                path = ROOT / "docs" / name
                if path.exists():
                    return Image.open(path)
        except Exception:
            pass
        from PIL import Image
        return Image.new("RGB", (64, 64), (124, 108, 255))

    def _start_tray(self) -> None:
        """Иконка в трее с меню — окно можно закрыть, сервер останется."""
        try:
            import pystray
        except ImportError:
            self._log("⚠️ pystray не установлен — трей недоступен "
                      "(pip install pystray pillow).")
            return

        def open_panel(icon, item):
            self.after(0, self._show_window)

        def toggle(icon, item):
            self.after(0, self._toggle)

        def quit_all(icon, item):
            self.after(0, self._quit)

        def set_mode(mode: str):
            def handler(icon, item):
                def apply() -> None:
                    cfg = settings.load()
                    cfg["mode"] = mode
                    settings.save(cfg)
                    self._log(f"🔁 Режим сбора: {self._mode_text()}")
                    try:
                        icon.update_menu()
                    except Exception:
                        pass
                self.after(0, apply)
            return handler

        def status_text(item):
            running = bool(self.proc and self.proc.poll() is None)
            return "⏹ Выключить сбор" if running else "▶ Включить сбор"

        def mode_checked(mode: str):
            def check(item) -> bool:
                return str(settings.load().get("mode") or "daily") == mode
            return check

        menu = pystray.Menu(
            pystray.MenuItem("Открыть панель", open_panel, default=True),
            pystray.MenuItem(status_text, toggle),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Режим: 2 раза в день (10:00, 19:00)",
                             set_mode("daily"),
                             checked=mode_checked("daily"), radio=True),
            pystray.MenuItem("Режим: каждые 15 минут (8:00–24:00)",
                             set_mode("frequent"),
                             checked=mode_checked("frequent"), radio=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выйти совсем", quit_all),
        )
        icon = pystray.Icon("rabota-msk", self._tray_image(),
                            "Работа MSK — сбор вакансий", menu)
        self.tray = icon
        threading.Thread(target=icon.run, daemon=True).start()

    def _hide_to_tray(self) -> None:
        """🙈 Крестик = свернуть в трей (сбор продолжает работать)."""
        if self.tray is None:
            self._stop_server()
            self.destroy()
            return
        self.withdraw()
        self._log("🙈 Свернулись в трей — сбор продолжается. "
                  "Иконка 💼 рядом с часами.")

    def _show_window(self) -> None:
        """👀 Вернуть окно из трея."""
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    # --- кнопки -------------------------------------------------------------
    def _toggle(self) -> None:
        if self.proc and self.proc.poll() is None:
            self._stop_server()
        else:
            self._start_server()

    def _start_server(self) -> None:
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
        self._last_start = time.time()
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

    def _maybe_autostart(self) -> None:
        """🚀 После открытия панели включаем сбор сразу (если так настроено)."""
        if self.proc and self.proc.poll() is None:
            return
        self._log("🚀 Автозапуск: включаю сбор сразу.")
        self._start_server()

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
            [sys.executable, str(ROOT / "_tools" / "вход_в_авито.py")],
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
                "Страница", "Адрес страницы пока не задан в настройках.\n"
                "Можно посмотреть локально кнопкой «Посмотреть у себя».")

    def _preview(self) -> None:
        """👁 Локальный предпросмотр страницы (без GitHub)."""
        try:
            con = store.connect()
            store.export_site(con, store.new_since(con))
            con.close()
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
        import functools
        import http.server
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

    def _mode_text(self) -> str:
        """📝 Человеческое имя текущего режима сбора."""
        cfg = settings.load()
        if str(cfg.get("mode") or "daily") == "frequent":
            return (f"каждые {int(cfg.get('interval_min') or 15)} мин "
                    f"({int(cfg.get('active_from') or 8)}:00–"
                    f"{int(cfg.get('active_to') or 24)}:00) + утро/вечер")
        hours = ", ".join(f"{int(h)}:00" for h in
                          (cfg.get("daily_hours") or [10, 19]))
        return f"2 раза в день ({hours})"

    # --- режим сбора ---------------------------------------------------------
    def _set_mode(self, mode: str) -> None:
        """🔁 Переключить режим: 2 раза в день ‖ каждые 15 минут."""
        cfg = settings.load()
        cfg["mode"] = mode
        settings.save(cfg)
        self._refresh_mode_ui()
        self._log(f"🔁 Режим сбора: {self._mode_text()}. "
                  f"Сбор подхватит в течение 30 секунд.")

    def _refresh_mode_ui(self) -> None:
        """Подсветить активную кнопку режима и подпись."""
        try:
            mode = str(settings.load().get("mode") or "daily")
            self.btn_mode_daily.state(["pressed"] if mode == "daily"
                                      else ["!pressed"])
            self.btn_mode_freq.state(["pressed"] if mode == "frequent"
                                     else ["!pressed"])
            self.lbl_mode.configure(text="сейчас: " + self._mode_text())
        except Exception:
            pass

    # --- автозагрузка -------------------------------------------------------
    def _autostart_enabled(self) -> bool:
        """Проверить запись автозагрузки в реестре (Run)."""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, RUN_NAME)
                return bool(value)
        except FileNotFoundError:
            return False
        except OSError:
            return (AUTOSTART_DIR / "Работа MSK.lnk").exists()

    def _set_autostart(self, on: bool) -> None:
        """🚀 Запись в реестре Run: панель стартует c Windows, без COM."""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
                if on:
                    winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ,
                                      self._autostart_command())
                else:
                    try:
                        winreg.DeleteValue(key, RUN_NAME)
                    except FileNotFoundError:
                        pass
            # прибрать возможный старый ярлык
            old = AUTOSTART_DIR / "Работа MSK.lnk"
            if old.exists():
                try:
                    old.unlink()
                except OSError:
                    pass
        except OSError as exc:
            self._log(f"⚠️ Автозагрузка не настроилась: {exc}")
            return
        if on:
            self._log("🚀 Автозапуск включён: панель откроется сама после "
                      "перезагрузки ПК.")
        else:
            self._log("🛑 Автозапуск выключен.")

    @staticmethod
    def _autostart_command() -> str:
        """Команда для реестра: pythonw + panel.py (в кавычках — пути с
        пробелами и кириллицей). Запускается свёрнуто в трей."""
        py = Path(sys.executable).with_name("pythonw.exe")
        if not py.exists():
            py = Path(sys.executable)
        return f'"{py}" "{ROOT / "panel" / "panel.py"}" --tray'

    # --- настройки ----------------------------------------------------------
    def _open_settings(self) -> None:
        win = tk.Toplevel(self)
        win.title("Настройки")
        win.configure(bg=BG)
        win.geometry("660x640")
        win.transient(self)

        cfg = settings.load()
        rows = [
            ("Запросы к Авито (по одному в строке)", "queries", "text"),
            ("Часы сбора «2 раза в день» (через запятую)", "daily_hours",
             "str"),
            ("Интервал «каждые 15 минут», минут", "interval_min", "int"),
            ("…собирать с часа (0–24)", "active_from", "int"),
            ("…и до часа (0–24, 24 = до полуночи)", "active_to", "int"),
            ("Минимальная зарплата ₽/мес (0 — все)", "min_salary_month", "int"),
            ("Telegram-токен (опция)", "telegram_token", "str"),
            ("Telegram chat_id", "telegram_chat", "str"),
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
                if key == "daily_hours":
                    value = ", ".join(str(int(h)) for h in
                                      (cfg.get(key) or [10, 19]))
                else:
                    value = str(cfg.get(key) if cfg.get(key) is not None
                                else "")
                var = tk.StringVar(value=value)
                ent = ttk.Entry(frame, textvariable=var, width=48)
                ent.grid(row=idx, column=1, sticky="we", pady=(6, 0))
                widgets[key] = var
        frame.columnconfigure(1, weight=1)

        tg = ttk.Frame(frame)
        tg.grid(row=len(rows), column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Button(tg, text="Проверить бота",
                   command=self._tg_check).pack(side="left")
        ttk.Button(tg, text="Привязать чат",
                   command=lambda: self._tg_bind(widgets)
                   ).pack(side="left", padx=(8, 0))
        ttk.Button(tg, text="Отправить тест",
                   command=lambda: self._tg_test(widgets)
                   ).pack(side="left", padx=(8, 0))

        auto_row = ttk.Frame(frame)
        auto_row.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="w",
                      pady=(12, 0))
        auto_var = tk.BooleanVar(value=self._autostart_enabled())
        tk.Checkbutton(
            auto_row, text="Запускать панель при включении компьютера "
                           "(автозагрузка)",
            variable=auto_var, bg=BG, fg=FG, activebackground=BG,
            activeforeground=FG, selectcolor=CARD,
            command=lambda: self._set_autostart(auto_var.get())
        ).pack(anchor="w")

        def save_and_close() -> None:
            new = dict(cfg)
            new["queries"] = [q.strip() for q in
                              widgets["queries"].get("1.0", "end").splitlines()
                              if q.strip()]
            for key in ("interval_min", "min_salary_month",
                        "active_from", "active_to"):
                try:
                    new[key] = max(0, int(widgets[key].get()))
                except (ValueError, tk.TclError):
                    pass
            new["interval_min"] = max(5, int(new.get("interval_min") or 15))
            new["active_from"] = min(24, max(0, int(new.get("active_from", 8))))
            new["active_to"] = min(24, max(0, int(new.get("active_to", 24))))
            # «10, 19» → [10, 19]
            hours = []
            for token in str(widgets["daily_hours"].get()).replace(";", ",") \
                    .split(","):
                token = token.strip()
                if token.isdigit():
                    hours.append(min(24, max(0, int(token))))
            new["daily_hours"] = sorted(set(hours)) or [10, 19]
            for key in ("telegram_token", "telegram_chat", "repo_url",
                        "repo_branch", "site_url"):
                new[key] = widgets[key].get().strip()
            settings.save(new)
            self.cfg = new
            self._refresh_mode_ui()
            self._log("⚙️ Настройки сохранены.")
            win.destroy()

        ttk.Button(frame, text="💾 Сохранить",
                   command=save_and_close).grid(row=len(rows) + 2, column=0,
                                                columnspan=2, pady=(16, 0))

    def _tg_values(self, widgets) -> tuple[str, str]:
        return (widgets["telegram_token"].get().strip(),
                widgets["telegram_chat"].get().strip())

    def _tg_check(self) -> None:
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
        # сторож: если сбор упал сам (не по кнопке) — поднимаем заново
        if (not running and self.proc is not None and not self._quitting
                and self.cfg.get("auto_restart", True)
                and time.time() - self._last_start > 60):
            self._log("♻️ Сбор завершился — перезапускаю через 15 секунд…")
            self.proc = None
            self.after(15000, self._maybe_autostart)
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
                    text = (f"🟢 Сбор работает · Собрано {last} · "
                            f"Следующее ~{nxt} · Новых: {st.get('fresh', 0)}"
                            f" · обновлено: {st.get('updated', 0)}")
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

    def _quit(self) -> None:
        """✖ Полный выход: гасим сбор, трей и окно."""
        self._quitting = True
        self._stop_server()
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.destroy()


def main() -> None:
    """Старт панели. `--tray` — открыться сразу в трее (для автозагрузки)."""
    tray_only = "--tray" in sys.argv
    app = Panel()
    if tray_only:
        app.after(500, app._hide_to_tray)
    app.mainloop()


if __name__ == "__main__":
    main()
