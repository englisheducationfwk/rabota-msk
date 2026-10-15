# -*- coding: utf-8 -*-
"""🚜 Пакет «Работа MSK»: сбор вакансий с Авито для мамы.

Модули:
    netguard  — прямой РУ-канал (мимо Happ) + страж страны IP
    avito     — поиск и детали вакансий живым браузером
    brain     — отсев ложных «горничных» и оценка «выгоды»
    store     — SQLite + срез JSON для страницы
    publish   — публикация данных на GitHub
    notify    — Telegram (опция)
    collect   — цикл сбора
    settings  — настройки (data/settings.json)
"""
