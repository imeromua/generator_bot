from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def back_to_main():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 На головну", callback_data="main_menu")]]
    )
