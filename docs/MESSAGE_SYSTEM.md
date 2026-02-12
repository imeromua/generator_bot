# 📨 Система повідомлень (FIX #25)

## 🎯 Огляд

Система повідомлень автоматично зберігає важливі повідомлення в історію користувача:

- ✅ **Success** - успішні операції
- ❌ **Error** - помилки
- ⚠️ **Warning** - попередження
- 🔔 **Alert** - важливі алерти
- ℹ️ **Info** - інформаційні повідомлення

Максимум **5 повідомлень** на користувача з авторотацією (найстаріші видаляються).

---

## 🛠️ API

### Database API (`database/db_api.py`)

```python
import database.db_api as db

# Додати повідомлення
db.add_message(user_id, "✅ Дані синхронізовано", "success")

# Отримати історію
messages = db.get_user_messages(user_id, limit=5)
# Returns: [(message_text, message_type, timestamp), ...]

# Очистити історію
db.clear_user_messages(user_id)

# Підрахувати повідомлення
count = db.get_message_count(user_id)
```

### Utility Functions (`utils/messaging.py`)

Зручні функції для автоматичного збереження:

```python
from utils.messaging import (
    notify_success,
    notify_error,
    notify_warning,
    notify_alert,
    notify_info,
    notify_all_users
)

# Успішна операція
notify_success(user_id, "✅ Дані синхронізовано")

# Помилка
notify_error(user_id, "❌ Помилка зв'язку з Google Sheets")

# Попередження
notify_warning(user_id, "⚠️ Паливо на нулі!")

# Алерт
notify_alert(user_id, "🔔 Час ТО: 2 год")

# Інфо
notify_info(user_id, "ℹ️ Генератор запущено")

# Broadcast всім користувачам
notify_all_users("🚨 Планове техобслуговування о 14:00", "warning")

# Broadcast тільки адмінам
notify_all_users("🔧 Оновлення системи", "info", admin_only=True)
```

---

## 📝 Приклади інтеграції

### 1. Синхронізація (`handlers/admin_parts/sync.py`)

```python
from utils.messaging import notify_success, notify_error

@router.callback_query(F.data == "sync_smart_execute")
async def sync_smart_execute(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    
    try:
        # Синхронізація...
        report = await asyncio.to_thread(bidirectional_sync, user_name)
        
        # ✅ Успіх
        notify_success(user_id, f"✅ Синхронізовано: {report.total_dates} дат")
        
    except Exception as e:
        # ❌ Помилка
        notify_error(user_id, f"❌ Помилка синхронізації: {str(e)[:50]}")
```

### 2. Алерти про паливо (`services/scheduler.py`)

```python
from utils.messaging import notify_warning, notify_all_users

async def check_fuel_level():
    st = db.get_state()
    fuel = float(st.get('current_fuel', 0.0))
    
    if fuel < 10.0:
        # Попередження всім
        notify_all_users(f"⚠️ Паливо на нулі: {fuel:.1f} л", "warning")
```

### 3. Алерти про ТО (`services/scheduler.py`)

```python
from utils.messaging import notify_alert, notify_all_users
import config

async def check_maintenance():
    st = db.get_state()
    total_hours = float(st.get('total_hours', 0.0))
    last_oil = float(st.get('last_oil_change', 0.0))
    
    hours_to_service = config.MAINTENANCE_LIMIT - (total_hours - last_oil)
    
    if hours_to_service <= 5.0:
        # Алерт адмінам
        notify_all_users(
            f"🔔 Час ТО: {hours_to_service:.1f} год", 
            "alert", 
            admin_only=True
        )
```

### 4. Операції зміни (`handlers/user_parts/shifts.py`)

```python
from utils.messaging import notify_success, notify_error

@router.callback_query(F.data.endswith("_start"))
async def start_shift(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    
    try:
        # Старт зміни...
        success, message = db.try_start_shift(shift_code, user_id, user_name)
        
        if success:
            notify_success(user_id, f"✅ Зміна {shift_code.upper()} запущена")
        else:
            notify_error(user_id, f"❌ {message}")
            
    except Exception as e:
        notify_error(user_id, f"❌ Помилка старту: {str(e)[:50]}")
```

### 5. Прийом палива (`handlers/user_parts/refill.py`)

```python
from utils.messaging import notify_success

@router.callback_query(F.data.startswith("drv_"))
async def fuel_driver_selected(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    
    # Збереження...
    db.update_fuel(float(liters), reason="refill", driver=driver, receipt=receipt)
    
    # ✅ Повідомлення
    notify_success(
        user_id, 
        f"✅ Прийнято {liters:.1f} л палива (Водій: {driver})"
    )
```

---

## 👥 UI компоненти

### Кнопка в головному меню

В `keyboards/builders.py` додано кнопку:

```python
kb.append([InlineKeyboardButton(text="📨 Повідомлення", callback_data="view_messages")])
```

### Обробники

В `handlers/common_parts/messages.py`:

- `view_messages` - перегляд історії
- `clear_messages` - очищення історії
- `main_menu` - повернення на головну

---

## 📊 Формат відображення

Повідомлення відображаються з часом:

- "щойно" (< 1 хв)
- "5 хв тому" (< 1 год)
- "2 год тому" (< 24 год)
- "вчора о 14:30"
- "11.02 10:15"

---

## 📦 База даних

Таблиця `user_messages`:

```sql
CREATE TABLE user_messages (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    message_text TEXT NOT NULL,
    message_type TEXT NOT NULL,  -- info, success, warning, error, alert
    timestamp TEXT NOT NULL
);

CREATE INDEX idx_user_messages_user_ts ON user_messages(user_id, timestamp DESC);
```

Авторотація: при досягненні 5 повідомлень найстаріше видаляється.

---

## ✅ Checklist інтеграції

- [x] Створено таблицю `user_messages`
- [x] Додано Messages API
- [x] Створено утиліти `utils/messaging.py`
- [x] Додано кнопку в головне меню
- [x] Створено обробники перегляду
- [x] Зареєстровано роутери
- [ ] **TODO**: Інтегрувати в синхронізацію
- [ ] **TODO**: Інтегрувати в алерти палива
- [ ] **TODO**: Інтегрувати в алерти ТО
- [ ] **TODO**: Інтегрувати в операції змін
- [ ] **TODO**: Інтегрувати в прийом палива

---

## 🔗 Links

- Database API: `database/api/messages.py`
- Utility Functions: `utils/messaging.py`
- UI Handlers: `handlers/common_parts/messages.py`
- Keyboards: `keyboards/builders.py`
