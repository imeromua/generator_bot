# 📱 Telegram Mini App — Документація по впровадженню

## Зміст

- [Огляд](#огляд)
- [Архітектура](#архітектура)
- [Вимоги](#вимоги)
- [Встановлення](#встановлення)
- [Налаштування](#налаштування)
- [Запуск](#запуск)
- [Розгортання на сервері](#розгортання-на-сервері)
- [HTTPS та домен](#https-та-домен)
- [Реєстрація Mini App в BotFather](#реєстрація-mini-app-в-botfather)
- [API ендпоінти](#api-ендпоінти)
- [Структура файлів](#структура-файлів)
- [Безпека](#безпека)
- [Оновлення](#оновлення)
- [Вирішення проблем](#вирішення-проблем)

---

## Огляд

**Generator Bot Mini App** — це вебзастосунок (Telegram WebApp), який працює безпосередньо всередині Telegram. Надає сучасний адаптивний інтерфейс для моніторингу стану генератора.

### Можливості:

| Функція | Опис |
|---------|------|
| 🏠 **Дашборд** | Статус генератора, паливо, мотогодини, зміни |
| 📅 **Графік** | Графік відключень з навігацією по датах |
| 🕘 **Події** | Журнал останніх подій (старт/стоп, заправки, ТО) |
| 🔧 **ТО** | Стан технічного обслуговування з прогрес-барами |

### Особливості:
- ✅ Адаптивний дизайн для мобільних пристроїв
- ✅ Інтеграція з темою Telegram (світла/темна)
- ✅ Автоматичне оновлення даних кожні 30 секунд
- ✅ Тижневий огляд графіку відключень
- ✅ Оцінка палива «на льоту» під час роботи генератора
- ✅ Повністю українською мовою

---

## Архітектура

```
┌───────────────────────────┐
│   Telegram (клієнт)       │
│   ┌───────────────────┐   │
│   │  Mini App (WebApp) │   │
│   │  HTML / CSS / JS   │   │
│   └────────┬──────────┘   │
│            │ HTTP/HTTPS    │
└────────────┼──────────────┘
             │
┌────────────▼──────────────┐
│  webapp_server.py          │
│  (aiohttp)                 │
│  ┌─────────┐ ┌──────────┐ │
│  │ Static  │ │ REST API │ │
│  │ Files   │ │ /api/*   │ │
│  └─────────┘ └────┬─────┘ │
│                   │        │
│  ┌────────────────▼─────┐  │
│  │  database.db_api     │  │
│  │  (SQLite / Postgres) │  │
│  └──────────────────────┘  │
└────────────────────────────┘
```

**Потік даних:**
1. Telegram відкриває Mini App за URL (`WEBAPP_URL`)
2. Mini App завантажує HTML/CSS/JS з `webapp_server.py`
3. JavaScript робить запити до REST API (`/api/*`)
4. Сервер читає дані з бази даних через `database.db_api`
5. Дані повертаються у форматі JSON

---

## Вимоги

- **Python** 3.10+
- **Залежності**: aiohttp (вже є в `requirements.txt`)
- **HTTPS** (обов'язково для Telegram WebApp)
- **Домен** з SSL-сертифікатом (Let's Encrypt або інший)
- База даних: SQLite або PostgreSQL (та ж, що і для бота)

> ⚠️ Telegram вимагає **HTTPS** для Mini App. HTTP працює тільки для локальної розробки.

---

## Встановлення

### 1. Залежності вже встановлені

Якщо бот вже працює — додаткових залежностей не потрібно. `aiohttp` входить до `requirements.txt`.

```bash
# Якщо ще не встановлено
pip install -r requirements.txt
```

### 2. Перевірте наявність файлів

```
webapp/
├── index.html      # Головна сторінка
├── css/
│   └── style.css   # Стилі
└── js/
    ├── api.js      # API-клієнт
    └── app.js      # Логіка інтерфейсу

webapp_server.py    # Веб-сервер
```

---

## Налаштування

### Параметри в `.env`

```env
# URL для Mini App (обов'язково для кнопки в боті)
WEBAPP_URL=https://your-domain.com

# Порт веб-сервера (за замовчуванням: 8080)
WEBAPP_PORT=8080

# Хост (за замовчуванням: 0.0.0.0)
WEBAPP_HOST=0.0.0.0
```

### Пояснення:

| Параметр | За замовч. | Опис |
|----------|-----------|------|
| `WEBAPP_URL` | *(порожньо)* | Публічний HTTPS URL вашого Mini App. Якщо порожньо — кнопка не з'являється |
| `WEBAPP_PORT` | `8080` | Порт для веб-сервера |
| `WEBAPP_HOST` | `0.0.0.0` | Хост для прослуховування |

---

## Запуск

### Локальна розробка

```bash
# 1. Запустіть бота (в окремому терміналі)
python main.py

# 2. Запустіть Mini App сервер
python webapp_server.py
```

Mini App буде доступний за адресою: `http://localhost:8080`

### Перевірка працездатності

```bash
# Перевірка статусу
curl http://localhost:8080/api/status

# Перевірка графіку
curl http://localhost:8080/api/schedule

# Перевірка подій
curl http://localhost:8080/api/events

# Перевірка ТО
curl http://localhost:8080/api/maintenance
```

---

## Розгортання на сервері

### Варіант 1: systemd сервіс (рекомендовано)

Створіть файл сервісу `/etc/systemd/system/generator-webapp.service`:

```ini
[Unit]
Description=Generator Bot Mini App
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/generator_bot
EnvironmentFile=/path/to/generator_bot/.env
ExecStart=/path/to/generator_bot/venv/bin/python webapp_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Активація:

```bash
sudo systemctl daemon-reload
sudo systemctl enable generator-webapp
sudo systemctl start generator-webapp
sudo systemctl status generator-webapp
```

### Варіант 2: Запуск через shell-скрипт

```bash
# Запуск в фоні
nohup python webapp_server.py > webapp.log 2>&1 &

# Зупинка
kill $(cat webapp.pid)
```

---

## HTTPS та домен

### Варіант 1: Nginx reverse proxy (рекомендовано)

Встановіть Nginx та налаштуйте проксі:

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Отримання SSL-сертифіката (Let's Encrypt):

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### Варіант 2: Caddy (автоматичний HTTPS)

```
your-domain.com {
    reverse_proxy localhost:8080
}
```

---

## Реєстрація Mini App в BotFather

1. Відкрийте [@BotFather](https://t.me/BotFather) в Telegram
2. Виберіть вашого бота
3. Натисніть **Bot Settings** → **Menu Button** → **Configure menu button**
4. Або використайте команди:

```
/setmenubutton
```

5. Введіть URL: `https://your-domain.com`
6. Введіть назву кнопки: `📱 Mini App`

### Додатково: Web App через BotFather

```
/newapp             # Створити нову Mini App
                    # Вкажіть URL: https://your-domain.com
                    # Вкажіть назву: Generator Dashboard
```

Після цього `WEBAPP_URL` у `.env` дозволить кнопку Mini App на дашборді бота.

---

## API ендпоінти

### `GET /api/status`

Поточний стан генератора.

**Відповідь:**
```json
{
    "status": "ON",
    "generator": "main",
    "generator_name": "Основний",
    "current_fuel": 45.2,
    "estimated_fuel": 42.1,
    "fuel_rate": 0.8,
    "total_hours": 156.3,
    "active_shift": "m_start",
    "completed_shifts": ["m"],
    "start_time": "2026-02-26T08:00:00",
    "work_start": "07:30",
    "work_end": "20:30"
}
```

### `GET /api/schedule?date=YYYY-MM-DD`

Графік відключень на дату. Без параметра `date` — повертає сьогоднішній.

**Відповідь:**
```json
{
    "date": "2026-02-26",
    "hours": [
        {"hour": 0, "label": "00:00 — 01:00", "off": false},
        {"hour": 1, "label": "01:00 — 02:00", "off": true}
    ]
}
```

### `GET /api/schedule/week`

Огляд графіку на тиждень.

**Відповідь:**
```json
{
    "days": [
        {"date": "2026-02-26", "weekday": "Чт", "off_hours": 4},
        {"date": "2026-02-27", "weekday": "Пт", "off_hours": 0}
    ]
}
```

### `GET /api/events?limit=N`

Останні N подій (за замовчуванням 20, максимум 100).

**Відповідь:**
```json
{
    "events": [
        {
            "event_type": "m_start",
            "timestamp": "2026-02-26T08:00:00",
            "actor": "Іванов І.І.",
            "value": "",
            "driver": "",
            "receipt": ""
        }
    ],
    "count": 1
}
```

### `GET /api/maintenance`

Стан технічного обслуговування.

**Відповідь:**
```json
{
    "generator": "main",
    "stats": {
        "oil_needed": 43.7,
        "spark_needed": 93.7,
        "maintenance_needed": 143.7,
        "total_hours": 156.3,
        "last_oil": 56.3,
        "last_spark": 6.3,
        "oil_interval": 100,
        "spark_interval": 100,
        "maintenance_interval": 300
    },
    "history": [
        {
            "id": 1,
            "date": "2026-02-20T10:00:00",
            "type": "oil",
            "hours": 100.0,
            "admin": "Петренко П.П."
        }
    ]
}
```

---

## Структура файлів

```
generator_bot/
├── webapp_server.py         # Веб-сервер (aiohttp)
├── webapp/
│   ├── index.html           # Головна HTML-сторінка
│   ├── css/
│   │   └── style.css        # Стилі (Telegram-тема, адаптивний)
│   └── js/
│       ├── api.js           # API-клієнт (fetch)
│       └── app.js           # Логіка інтерфейсу
├── docs/
│   └── MINIAPP.md           # Ця документація
└── .env                     # Конфігурація (WEBAPP_URL, WEBAPP_PORT)
```

---

## Безпека

### Валідація Telegram initData

Сервер підтримує валідацію `initData` від Telegram WebApp через HMAC-SHA256:

1. Клієнт надсилає `initData` у заголовку `X-Telegram-Init-Data`
2. Сервер перевіряє підпис за алгоритмом Telegram
3. Витягує інформацію про користувача

> ⚠️ Поточна версія — лише для читання (read-only). API не надає операцій запису, тому ризики мінімальні.

### Рекомендації:

- ✅ Завжди використовуйте **HTTPS**
- ✅ Обмежте доступ через Nginx (IP whitelist, rate limiting)
- ✅ Не зберігайте `BOT_TOKEN` у фронтенд-коді
- ✅ Регулярно оновлюйте SSL-сертифікати
- ❌ Не відкривайте порт `WEBAPP_PORT` напряму в інтернет — використовуйте reverse proxy

---

## Оновлення

### Оновлення Mini App

```bash
# 1. Оновіть файли (git pull або вручну)
cd /path/to/generator_bot
git pull

# 2. Перезапустіть веб-сервер
sudo systemctl restart generator-webapp
```

### Оновлення без простою

Оскільки Mini App — це статичні файли + простий API, оновлення зазвичай миттєве:

```bash
# Оновіть файли, потім
sudo systemctl restart generator-webapp
```

---

## Вирішення проблем

### Mini App не відкривається в Telegram

1. Перевірте що `WEBAPP_URL` вказує на HTTPS
2. Перевірте що сертифікат SSL валідний
3. Перевірте що веб-сервер доступний ззовні

```bash
curl -I https://your-domain.com
```

### Помилка "Завантаження даних..."

1. Перевірте що `webapp_server.py` запущений
2. Перевірте що база даних доступна
3. Перегляньте логи:

```bash
sudo journalctl -u generator-webapp -f
```

### Кнопка Mini App не відображається

Переконайтесь що `WEBAPP_URL` у `.env` не порожній і бот перезапущений:

```env
WEBAPP_URL=https://your-domain.com
```

### CORS-помилки

Сервер автоматично додає CORS-заголовки. Якщо проблеми залишаються — перевірте конфігурацію Nginx (не дублювати CORS-заголовки).

---

## Контакти

Автор: [@imeromua](https://github.com/imeromua)

Проєкт: [generator_bot](https://github.com/imeromua/generator_bot)
