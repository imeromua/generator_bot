from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
import config

class WhitelistMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # Отримуємо ID користувача (з повідомлення або кліку)
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        else:
            return await handler(event, data)

        # 1. Адміни проходять завжди
        if user_id in config.ADMIN_IDS:
            return await handler(event, data)

        # 2. Якщо це команда /start і відкрита реєстрація - пускаємо
        if isinstance(event, Message) and event.text == "/start" and config.REGISTRATION_OPEN:
            return await handler(event, data)

        # 3. Перевірка Білого списку (Whitelist)
        if user_id in config.WHITELIST_IDS:
            return await handler(event, data)

        # 4. Якщо нічого не підійшло - БЛОКУЄМО
        if isinstance(event, Message):
            await event.answer(f"⛔ <b>Доступ заборонено.</b>\nВаш ID: <code>{user_id}</code>\nЗверніться до адміністратора.")
        elif isinstance(event, CallbackQuery):
            await event.answer("⛔ У вас немає прав доступу.", show_alert=True)
        
        # Перериваємо обробку (handler не викликається)
        return