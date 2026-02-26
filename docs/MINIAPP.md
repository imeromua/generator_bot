# 📱 Mini App — Документація з впровадження

Telegram Mini App для бота управління генератором. Надає зручний веб-інтерфейс для перегляду стану генератора, графіків відключень, подій та технічного обслуговування.

---

## 📋 Зміст

- [Огляд](#-огляд)
- [Архітектура](#-архітектура)
- [Вимоги](#-вимоги)
- [Встановлення](#-встановлення)
- [Налаштування](#-налаштування)
- [API ендпоінти](#-api-ендпоінти)
- [Безпека](#-безпека)
- [Інтерфейс](#-інтерфейс)
- [Розгортання](#-розгортання)
- [Усунення проблем](#-усунення-проблем)

---

## 🔍 Огляд

Mini App — це веб-додаток, який працює всередині Telegram через [Telegram WebApp API](https://core.telegram.org/bots/webapps). Він надає зручний сучасний інтерфейс для:

- **Дашборд**: стан генератора, рівень палива, мотогодини, активна зміна
- **Графік відключень**: 24-годинна сітка з кольоровим кодуванням
- **Журнал подій**: останні події (старти/стопи, заправки, ТО)
- **Технічне обслуговування**: статус ТО, прогрес-бари, історія
- **Генератори**: інформація про основний та аварійний генератори

### Переваги Mini App:

| Функція | Telegram чат | Mini App |
|---------|-------------|----------|
| Перегляд стану | Текстове повідомлення | Візуальний дашборд |
| Графік | Текстовий список | Кольорова сітка |
| ТО | Текстові числа | Прогрес-бари |
| Оновлення | Нове повідомлення | Автооновлення |
| Теми | Фіксований | Адаптується під тему Telegram |

---

## 🏗 Архітектура

```
┌─────────────────────────────────────────┐
│           Telegram клієнт               │
│  ┌─────────────┐  ┌──────────────────┐  │
│  │  Bot чат     │  │  Mini App (WebApp)│  │
│  └──────┬──────┘  └────────┬─────────┘  │
└─────────┼─────────────────┼─────────────┘
          │                  │
          │ Polling          │ HTTPS
          │                  │
┌─────────┼─────────────────┼─────────────┐
│         │    Сервер бота   │             │
│  ┌──────┴──────┐  ┌───────┴──────────┐  │
│  │ aiogram Bot │  │ aiohttp WebServer│  │
│  │ (handlers)  │  │ (webapp API)     │  │
│  └──────┬──────┘  └───────┬──────────┘  │
│         │                  │             │
│         └──────┬───────────┘             │
│         ┌──────┴──────┐                  │
│         │  Database   │                  │
│         │  (SQLite/PG)│                  │
│         └─────────────┘                  │
└──────────────────────────────────────────┘
```

### Компоненти:

1. **Frontend** (`webapp/`): Статичний SPA (HTML/CSS/JS)
   - `index.html` — головна сторінка
   - `css/style.css` — стилі з підтримкою тем Telegram
   - `js/app.js` — логіка додатку

2. **Backend API** (`handlers/webapp_api.py`): REST ендпоінти
   - Обслуговується aiohttp паралельно з ботом
   - Аутентифікація через Telegram WebApp initData

3. **Інтеграція** (`main.py`): Запуск веб-сервера разом з ботом

---

## 📦 Вимоги

- **Python 3.11+**
- Всі залежності з `requirements.txt` (aiohttp вже включено)
- **HTTPS** для production (Telegram вимагає HTTPS для WebApp)
- **Доменне ім'я** з SSL-сертифікатом

> ⚠️ Для локальної розробки можна використовувати HTTP, але Telegram Mini App вимагає HTTPS в production.

---

## 🛠 Встановлення

### 1. Оновіть залежності

```bash
pip install -r requirements.txt
```

Нових залежностей не потрібно — `aiohttp` вже є в `requirements.txt`.

### 2. Налаштуйте `.env`

Додайте параметри Mini App до вашого `.env` файлу:

```env
# Mini App (Telegram WebApp)
WEBAPP_URL=https://your-domain.com/webapp
WEBAPP_HOST=0.0.0.0
WEBAPP_PORT=8080
```

### 3. Запустіть бота

```bash
python main.py
```

Веб-сервер Mini App запуститься автоматично разом з ботом.

---

## ⚙️ Налаштування

### Параметри `.env`

| Параметр | Опис | За замовчуванням |
|----------|------|-----------------|
| `WEBAPP_URL` | Публічний URL Mini App | `""` (вимкнено) |
| `WEBAPP_HOST` | Адреса прослуховування веб-сервера | `0.0.0.0` |
| `WEBAPP_PORT` | Порт веб-сервера | `8080` |

### Як працює:

1. Якщо `WEBAPP_URL` задано — в дашборді бота з'являється кнопка "📱 Mini App"
2. Веб-сервер запускається на `WEBAPP_HOST:WEBAPP_PORT`
3. API ендпоінти доступні за шляхом `/api/*`
4. Статичні файли (HTML/CSS/JS) обслуговуються з директорії `webapp/`

### Налаштування BotFather:

Для коректної роботи Mini App налаштуйте бота через [@BotFather](https://t.me/BotFather):

1. `/mybots` → Оберіть бота → Bot Settings → Menu Button
2. Встановіть URL: `https://your-domain.com/webapp`
3. Встановіть текст: `📱 Mini App`

---

## 📡 API ендпоінти

Всі ендпоінти вимагають заголовок `X-Telegram-Init-Data` з валідними даними Telegram WebApp.

### `GET /api/status`

Стан генератора.

**Відповідь:**
```json
{
    "status": "ON",
    "active_shift": "m_start",
    "active_shift_name": "🌅 Зміна 1",
    "start_time": "08:30",
    "current_fuel": 85.5,
    "total_hours": 1234.5,
    "active_generator": "main",
    "generator_name": "🔋 Основний",
    "completed_shifts": ["m"],
    "is_admin": true,
    "fuel_consumption": 5.3
}
```

### `GET /api/schedule`

Графік відключень на сьогодні.

**Відповідь:**
```json
{
    "date": "2026-02-26",
    "hours": [
        {"hour": 0, "label": "00:00", "is_off": false},
        {"hour": 1, "label": "01:00", "is_off": true},
        ...
    ]
}
```

### `GET /api/events`

Останні події. Параметр `limit` (за замовчуванням: 20, максимум: 50).

**Відповідь:**
```json
{
    "events": [
        {
            "type": "m_start",
            "icon": "🌅",
            "timestamp": "2026-02-26 08:30:00",
            "user": "Іванов І.І.",
            "value": "",
            "driver": "",
            "receipt": "",
            "generator": "main"
        }
    ]
}
```

### `GET /api/maintenance`

Стан технічного обслуговування.

**Відповідь:**
```json
{
    "generator": "main",
    "generator_name": "🔋 Основний",
    "oil_interval": 100,
    "spark_interval": 100,
    "maintenance_interval": 300,
    "total_hours": 1234.5,
    "oil_used": 45.2,
    "oil_remaining": 54.8,
    "spark_used": 45.2,
    "spark_remaining": 54.8,
    "maintenance_remaining": 165.5,
    "history": [
        {
            "date": "2026-02-20 10:00:00",
            "type": "🛢 Мастило",
            "hours": 1200.0,
            "admin": "Адмін"
        }
    ]
}
```

### `GET /api/generators`

Інформація про всі генератори.

**Відповідь:**
```json
{
    "active": "main",
    "generators": {
        "main": {
            "name": "🔋 Основний",
            "total_hours": 1234.5,
            "last_oil_change": 45.2,
            "last_spark_change": 45.2,
            "is_active": true
        },
        "emergency": {
            "name": "⚠️ Аварійний",
            "total_hours": 56.3,
            "last_oil_change": 12.1,
            "last_spark_change": 12.1,
            "is_active": false
        }
    },
    "current_fuel": 85.5,
    "fuel_consumption": 5.3,
    "emergency_fuel_consumption": 6.5
}
```

---

## 🔐 Безпека

### Аутентифікація

Mini App використовує [Telegram WebApp Init Data](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app) для аутентифікації:

1. Telegram передає `initData` при відкритті Mini App
2. Frontend надсилає `initData` в заголовку `X-Telegram-Init-Data`
3. Backend перевіряє підпис HMAC-SHA256 з використанням `BOT_TOKEN`
4. Перевіряється свіжість `auth_date` (не старше 24 годин)

### CORS

API дозволяє запити з будь-якого джерела (`Access-Control-Allow-Origin: *`), оскільки аутентифікація здійснюється через Telegram initData, а не cookies.

### Рекомендації:

- ✅ Використовуйте HTTPS з валідним SSL-сертифікатом
- ✅ Обмежте доступ до порту `WEBAPP_PORT` через firewall
- ✅ Використовуйте reverse proxy (nginx) перед aiohttp
- ❌ Не відкривайте `WEBAPP_PORT` напряму в інтернет

---

## 🎨 Інтерфейс

### Сторінки

#### 🏠 Дашборд (Головна)
- Індикатор стану генератора (ON/OFF з анімацією)
- Інформація про активну зміну та час старту
- Рівень палива з прогрес-баром
- Мотогодини, витрата палива
- Кількість завершених змін

#### 📅 Графік відключень
- 24-годинна сітка з кольоровим кодуванням
- 🟢 Зелений — електрика є
- 🔴 Червоний — відключення
- Поточна година виділена рамкою

#### 🕘 Останні події
- Хронологічний список подій
- Іконки для різних типів подій
- Метадані: оператор, водій, чек

#### 🛠 Технічне обслуговування
- Прогрес-бари для мастила та свічок
- Колір змінюється: 🔵 норма → 🟡 увага → 🔴 критично
- Залишок годин до ТО
- Історія виконаних ТО

#### 🔄 Генератори
- Картки основного та аварійного генераторів
- Активний генератор виділений рамкою
- Статистика: мотогодини, ТО
- Спільний бак палива

### Теми

Mini App автоматично адаптується під тему Telegram (світла/темна) через CSS-змінні:

```css
var(--tg-theme-bg-color)        /* Колір фону */
var(--tg-theme-text-color)      /* Колір тексту */
var(--tg-theme-button-color)    /* Колір кнопок */
var(--tg-theme-hint-color)      /* Колір підказок */
```

### Автооновлення

Дашборд автоматично оновлюється кожні 30 секунд.

---

## 🚀 Розгортання

### Варіант 1: Прямий запуск (розробка)

```bash
# 1. Налаштуйте .env
WEBAPP_URL=http://localhost:8080/webapp
WEBAPP_PORT=8080

# 2. Запустіть бота
python main.py
```

### Варіант 2: Nginx reverse proxy (production)

#### Конфігурація Nginx:

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # Mini App
    location /webapp {
        proxy_pass http://127.0.0.1:8080/webapp;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8080/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /css/ {
        proxy_pass http://127.0.0.1:8080/css/;
    }

    location /js/ {
        proxy_pass http://127.0.0.1:8080/js/;
    }
}
```

#### `.env` для production:

```env
WEBAPP_URL=https://your-domain.com/webapp
WEBAPP_HOST=127.0.0.1
WEBAPP_PORT=8080
```

### Варіант 3: Systemd сервіс

Створіть файл `/etc/systemd/system/generator-bot.service`:

```ini
[Unit]
Description=Generator Bot
After=network.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/opt/generator_bot
ExecStart=/opt/generator_bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable generator-bot
sudo systemctl start generator-bot
```

### Варіант 4: Використання shell-скриптів

```bash
# Запуск
./start.sh

# Зупинка
./stop.sh

# Перезапуск
./restart.sh

# Статус
./status.sh
```

---

## 🔧 Усунення проблем

### Mini App не відкривається

1. Перевірте, що `WEBAPP_URL` в `.env` правильний
2. Перевірте, що веб-сервер запущений (шукайте в логах `📱 Mini App веб-сервер запущено`)
3. Перевірте HTTPS сертифікат (Telegram вимагає валідний SSL)
4. Переконайтесь, що порт відкритий у firewall

### Помилка авторизації (401)

1. Відкривайте Mini App тільки через кнопку в Telegram боті
2. Перевірте, що `BOT_TOKEN` правильний
3. Переконайтесь, що час на сервері синхронізовано (NTP)

### Дані не завантажуються

1. Перевірте, що база даних ініціалізована
2. Перевірте логи бота на помилки
3. Відкрийте Dev Tools в браузері (F12) та перевірте Network вкладку

### API повертає 500

1. Перевірте логи бота (`./logs.sh`)
2. Переконайтесь, що всі таблиці бази даних створені
3. Перевірте з'єднання з базою даних

---

## 📝 Структура файлів

```
webapp/
├── index.html          # Головна сторінка SPA
├── css/
│   └── style.css       # Стилі (Telegram theme-aware)
└── js/
    └── app.js          # Логіка додатку

handlers/
└── webapp_api.py       # REST API ендпоінти

docs/
└── MINIAPP.md          # Ця документація
```

---

## 📄 Ліцензія

MIT License
