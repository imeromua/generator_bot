# 🗄️ База даних: Структура та Моделі

Цей документ автоматично згенерований на основі аналізу коду (`database/models.py`). 
Проєкт використовує абстракцію над СУБД для паралельної підтримки **SQLite** (для розробки) та **PostgreSQL** (через `psycopg_pool` для production).

> ⚠️ Усі нові SQL запити повинні писатись із використанням плейсхолдерів `?`, які автоматично конвертуються в `%s` для PostgreSQL через функцію `_translate_qmarks()`.

## 📊 Таблиці

### ⛽ Core (Логіка генератора та подій)
* **`generator_state`** (K/V сховище): Поточний стан (кеш) бота та генераторів.
  * Структура: `key` (TEXT PK), `value` (TEXT).
  * Ключові стани: `total_hours`, `current_fuel`, `status` (ON/OFF), `active_shift`, `active_generator` (main/emergency), параметри ТО.
* **`logs`**: Канонічний журнал всіх подій (створення змін, заправки).
  * Колонки: `id`, `event_type`, `timestamp`, `user_name`, `value`, `driver_name`, `receipt_number`, `is_synced` (чи вивантажено в Sheets), `generator_id` (main/emergency).
* **`maintenance`**: Записи про технічне обслуговування (мастило/свічки).
  * Колонки: `id`, `date`, `type`, `hours`, `admin`, `generator_id`.

### 👥 Користувачі та Довідники
* **`users`**: Всі користувачі бота та вебу.
  * Колонки: `user_id` (PK, Telegram ID), `username`, `first_name`, `last_name`, `full_name`, `role` (user/admin тощо), `is_active`, `registered_at`, `email`, `password_hash`, `web_login`, логіка блокування.
* **`drivers`** / **`personnel_names`**: Довідники імен водіїв та персоналу.
* **`user_personnel`**: Зв'язка `user_id` <-> `personnel_name`.

### 📝 Розклади та Планування
* **`schedule`**: Графік відключень електроенергії (стара логіка чи просто дата/година). `date`, `hour`, `is_off`.
* **`shift_schedule`**: Планування змін персоналу (`date`, `shift_type`, `assigned_personnel_id`, `status`).
* **`fuel_orders`**: Замовлення палива (`created_at`, `requested_by`, `amount_liters`, `status` тощо).

### 📱 Системні / Веб-Авторизація / UI
* **`user_ui`**: Відстежує "Single-Window" інтерфейс бота (`chat_id`, `message_id`), щоб бот не спамив, а оновлював одне повідомлення.
* **`user_messages`**: Історія користувацьких повідомлень.
* **`admin_audit_log`**: Журнал дій адміністраторів (зміна налаштувань, бази).
* **`notification_preferences`**: Персональні налаштування пуш-сповіщень.
* **`web_sessions`** та **`web_password_reset`**: Таблиці обробки JWT/сесій для доступу через веб (через логін/пароль чи Telegram Mini App).

## 🔑 Індексування
У базі створено багато оптимізованих індексів, зокрема `idx_logs_timestamp`, `idx_logs_event_type`, `idx_logs_generator_id`. Під час написання важких `SELECT` запитів переконайтеся, що вони йдуть по індексах, особливо у подіях (`logs`).
