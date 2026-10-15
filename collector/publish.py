# -*- coding: utf-8 -*-
"""⬆️ Публикация данных на GitHub — тем же способом, что и раньше (git).

Схема: локальный клон в data/git-data, ветка repo_branch («data»),
один коммит, который обновляется amend-ом и уезжает force-push-ом.
Никакого замусоривания истории — репозиторий всегда чистый.

Страница берёт свежий JSON по адресу
    https://raw.githubusercontent.com/<user>/<repo>/<branch>/vacancies.json
подставляя метку времени — так кэш CDN не мешает свежести.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLONE_DIR = ROOT / "data" / "git-data"


def _git(args: list[str], cwd: Path, timeout: int = 120) -> tuple[int, str]:
    """🖥️ Запуск git (без интерактивных подсказок — панель не шутит)."""
    env = {"GIT_TERMINAL_PROMPT": "0"}
    try:
        done = subprocess.run(
            ["git"] + args, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout, env={**__import__("os").environ, **env},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (done.stdout or "") + (done.stderr or "")
        return done.returncode, out.strip()
    except Exception as exc:  # noqa: BLE001
        return 1, f"{type(exc).__name__}: {exc}"


def raw_url(repo_url: str, branch: str) -> str:
    """🌐 Адрес сырого JSON (то, что тянет страница)."""
    repo = repo_url.rstrip("/")
    for prefix in ("https://github.com/", "git@github.com:"):
        if repo.startswith(prefix):
            repo = repo[len(prefix):]
            break
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"https://raw.githubusercontent.com/{repo}/{branch}/vacancies.json"


def publish(repo_url: str, branch: str, payload: dict,
            log=print) -> tuple[bool, str]:
    """📤 Обновить JSON в ветке данных (amend + force push)."""
    if not repo_url.strip():
        return False, "Не задан адрес репозитория"
    DATA = CLONE_DIR
    if not (DATA / ".git").exists():
        code, out = _git(["clone", "--depth", "1", repo_url, str(DATA)],
                         ROOT)
        if code != 0:
            return False, f"Клон не получился: {out[-300:]}"
    # ветка данных: либо уже на ней, либо создаём сироту с нуля
    code, _ = _git(["rev-parse", "--verify", branch], DATA)
    if code != 0:
        _git(["checkout", "--orphan", branch], DATA)
        _git(["rm", "-rf", "--cached", "."], DATA)
    else:
        _git(["checkout", branch], DATA)
    target = DATA / "vacancies.json"
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if target.exists() and target.read_text(encoding="utf-8") == text:
        return True, "Без изменений (пропущено)"
    target.write_text(text, encoding="utf-8")
    stamp = time.strftime("%d.%m.%Y %H:%M")
    _git(["add", "vacancies.json"], DATA)
    code, out = _git(["commit", "--amend", "-m",
                      f"Данные: {stamp}"], DATA)
    if code != 0:
        code, out = _git(["commit", "-m", f"Данные: {stamp}"], DATA)
        if code != 0:
            return False, f"Коммит не получился: {out[-300:]}"
    code, out = _git(["push", "--force", "origin", branch], DATA)
    if code != 0:
        return False, f"Push не получился: {out[-300:]}"
    log(f"   ⬆️ Данные на GitHub: {stamp}")
    return True, stamp


def clear_clone() -> None:
    """Забыть локальный клон (если репозиторий перенастроили)."""
    shutil.rmtree(CLONE_DIR, ignore_errors=True)
