# generator_bot

Telegram-бот для ведення роботи генератора: відкриття/закриття змін, облік палива, графік відключень, адмін-функції та синхронізація з Google Sheets. [cite:232]

## Можливості
- Зміни: послідовні **m/d/e** (ранок/день/вечір) + `x` (екстра), старт/стоп з логуванням подій. [cite:232]
- Ранковий брифінг (юзерам, не адмінам) у час `BRIEF_TIME`: графік відключень за сьогодні, паливо/залишок у годинах, до ТО, підсумок вчорашніх змін. [cite:207][cite:231]
- Авто-закриття зміни о `WORK_END` (якщо стан лишився `ON`) + сповіщення адмінам. [cite:207][cite:231]
- Нагадування адмінам «натисніть СТОП» за `STOP_REMINDER_MIN` хв до `WORK_END`, якщо генератор ще в стані `ON`. [cite:207][cite:231]
- Алерти по паливу адмінам при падінні нижче `FUEL_ALERT_THRESHOLD` з анти-спамом `FUEL_ALERT_COOLDOWN_MIN` та кнопкою «Паливо замовлено». [cite:207][cite:231]
- Google Sheets sync: окрема вкладка журналу подій (`LOGS_SHEET_NAME`) з idempotent-записом (1 `log_id` = 1 рядок). [cite:212][cite:231]
- Заправки (refill) синхронізуються idempotent-агрегацією за дату (сума літрів + чеки + водії). [cite:212]
- Парсер повідомлень ДТЕК: адмін може надіслати текст — бот запропонує застосувати знайдені діапазони відключення. [cite:227]

## Залежності
Встановлення залежностей:

```bash
pip install -r requirements.txt
```

Проєкт використовує `aiogram` (v3), `aiohttp`, `gspread` та `google-auth*`, а також `python-dotenv`, `pytz`, `pandas`, `openpyxl`. [cite:229]

## Налаштування
### 1) .env
Скопіюйте `.env.example` у `.env` і заповніть значення. [cite:231]

Обов’язково:
- `BOT_TOKEN` — токен Telegram-бота. [cite:231]
- `SHEET_ID_PROD` — ID Google Spreadsheet для PROD. [cite:231]
- `SHEET_ID_TEST` — ID Google Spreadsheet для TEST. [cite:231]
- `ADMINS` — Telegram ID адмінів через кому. [cite:231]

Часті налаштування:
- `MODE` = `TEST` або `PROD` (дефолт: `TEST`). [cite:231]
- `SHEET_NAME` — назва основної вкладки (worksheet) (дефолт: `ЛЮТИЙ`). [cite:231]
- `LOGS_SHEET_NAME` — назва вкладки журналу подій (дефолт: `ПОДІЇ`). [cite:231]
- `TIMEZONE` — (дефолт: `Europe/Kyiv`). [cite:231]
- `WORK_START`, `WORK_END`, `BRIEF_TIME` — часи роботи/брифінгу. [cite:231]
- `FUEL_RATE` — витрата палива (л/год). [cite:231]
- `FUEL_ALERT_THRESHOLD`, `FUEL_ALERT_COOLDOWN_MIN` — поріг та анти-спам алертів. [cite:231]
- `STOP_REMINDER_MIN` — за скільки хвилин до `WORK_END` нагадувати про «СТОП». [cite:231]

### 2) service_account.json
Покладіть `service_account.json` у корінь проєкту (поруч із `main.py`) — він використовується для доступу до Google Sheets. [cite:231][cite:226]

Також надайте доступ до Google Spreadsheet email-адресі service account (вона всередині JSON). [cite:232]

### 3) Вимоги до таблиці
- Бот знаходить рядок “сьогодні” у колонці A. [cite:212]
- Список водіїв читається з колонки **AB (28)**, персонал — з **AC (29)**. [cite:212]

## Запуск
```bash
python main.py
```

Під час запуску стартують фонові процеси синхронізації з Google Sheets (`sync_loop`) та планувальник (`scheduler_loop`). [cite:227]

## Команди
- `/start` — головне меню. [cite:232]

## Безпека
Не комітьте `.env` та `service_account.json` у репозиторій. [cite:232]
