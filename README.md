# 🕷️ SPIDER V8 — Telegram Graph Intelligence & AI Automation

Веб-платформа на **FastAPI + Telethon + Google Gemini** для сбора, анализа и визуализации графа связей Telegram-каналов, с умным мастером настройки профилей, Google Sniper и real-time мониторингом через WebSocket.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Telethon](https://img.shields.io/badge/Telethon-MTProto-26A5E4?logo=telegram&logoColor=white)
![Gemini](https://img.shields.io/badge/Google_Gemini-AI_Tagging-8E75B2?logo=googlegemini&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-Database-003B57?logo=sqlite&logoColor=white)
![Selenium](https://img.shields.io/badge/Selenium-Google_Sniper-43B02A?logo=selenium&logoColor=white)

---

## 🎬 Видеодемонстрация

📹 **[Смотреть демо-видео (`assets/demo.mp4`)](./assets/demo.mp4)**

*(Совет для GitHub: при редактировании `README.md` на сайте перетащите `assets/demo.mp4` в текст **отдельным абзацем с пустыми строками сверху и снизу** — GitHub заменит ссылку на встроенный видеоплеер.)*

---

## ✨ Основные возможности

- **📊 Dashboard & Live Logs (`dashboard.html`)** — управление несколькими профилями, статистика БД (`Approved`, `Rejected`, `Queue`, `Leads`), размер базы и потоковый вывод логов через **WebSocket (`/ws`)**.
- **🔗 Graph AI View (`index.html`)** — интерактивный граф связей между каналами (упоминания, репосты), макро/микро-режимы и авто-тегирование контента через **Google Gemini API**.
- **🎯 Google Sniper (`sniper.html`)** — поиск Telegram-каналов по Google Dorks (`selenium` / `undetected-chromedriver`), проверка через `t.me/s/`, подсчёт подписчиков и проверка открытых комментариев.
- **🪄 Smart Wizard (`wizard.html`)** — пошаговая настройка аккаунта: импорт `tdata`/сессий, тест прокси (SOCKS5/HTTP), проверка статуса в `@SpamBot`, AI-генерация имени/био и превью комментариев через Gemini.
- **🔑 Keywords (`keywords.html`)** — управление белыми и чёрными списками ключевых слов для фильтрации каналов.
- **⚙️ Settings (`settings.html`)** — глобальные лимиты парсинга, настройка Gemini API Key и прокси, управление профилями и аватарами (`Pillow`).

---

## 🏗 Архитектура

```mermaid
flowchart LR
    UI[Web UI: Dark Glassmorphism\nHTML / CSS / Vanilla JS] <-->|REST + WebSocket| API[FastAPI + Uvicorn\nweb_server.py]
    API --> DB[(SQLite\ndatabase.py)]
    API --> CORE[SpiderWorker\nTelethon MTProto]
    API --> SNIPER[Google Sniper\nSelenium / BS4]
    API --> AI[Google Gemini API\nAuto-Tagging & Copywriting]
    CORE --> TG[Telegram API\nvia SOCKS5 / HTTP Proxy]
```

---

## 📸 Интерфейс

### Dashboard & Live Activity Log
![Dashboard](assets/01_dashboard.png)

### Graph AI View
![Graph AI View](assets/02_graph_ai.png)

### Google Sniper
![Google Sniper](assets/03_sniper.png)

### Smart Wizard
![Smart Wizard](assets/04_wizard.png)

### Keywords & Settings
| Keywords | Settings |
|---|---|
| ![Keywords](assets/05_keywords.png) | ![Settings](assets/06_settings.png) |

---

## 🚀 Установка и запуск

### 1. Клонирование и зависимости

```bash
git clone https://github.com/vztyz/spider-v8.git
cd spider-v8
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux / macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Запуск

```bash
python main.py
```

Сервер поднимется на `http://127.0.0.1:8050/dashboard.html` и автоматически откроет интерфейс в браузере.

### 3. Первичная настройка

1. Откройте вкладку **Settings** и укажите ваш **Gemini API Key** (и прокси, если требуется).
2. Создайте профиль или импортируйте сессию через **Smart Wizard** (`api_id`, `api_hash`, прокси).
3. Настройте фильтры во вкладке **Keywords** и запускайте сбор с **Dashboard** или через **Google Sniper**.

---

## 📁 Структура проекта

```text
├── main.py              # Точка входа (Uvicorn + автооткрытие браузера)
├── web_server.py        # FastAPI-приложение, REST API, WebSocket и интеграция с Gemini
├── spider_core.py       # Асинхронный MTProto-воркер на базе Telethon
├── database.py          # Потокобезопасный менеджер SQLite и схема таблиц
├── gogle.py             # Google Sniper (Selenium / undetected-chromedriver + BS4)
├── requirements.txt     # Зависимости проекта
├── .gitignore           # Исключение .env, .session, .db, .csv и кэша
├── assets/              # Скриншоты и демо-видео
└── web/                 # Фронтенд (HTML / CSS / JS)
```

---

## 🔒 Безопасность

- Файлы сессий (`*.session`), `tdata/`, базы данных (`*.db`), выгрузки (`*.csv`) и `.env` исключены из репозитория через `.gitignore`.
- Используйте собственные API-ключи (`api_id`, `api_hash`, `GEMINI_API_KEY`) и соблюдайте правила использования соответствующих платформ.
