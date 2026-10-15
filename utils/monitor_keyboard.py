from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


MAIN_MENU_ACTIONS = {
    '➕ Добавить чат': 'monitor:add',
    '📋 Мои чаты': 'monitor:list:0',
    '🔎 Фильтры': 'monitor:filters',
    '⚙️ Продвинутые настройки': 'monitor:settings',
}


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
        for row in rows
    ])


def monitor_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='➕ Добавить чат'), KeyboardButton(text='📋 Мои чаты')],
            [KeyboardButton(text='🔎 Фильтры')],
            [KeyboardButton(text='⚙️ Продвинутые настройки')],
        ],
        resize_keyboard=True, is_persistent=True, one_time_keyboard=False,
    )


def cancel_keyboard():
    return keyboard([[("Отмена", "monitor:cancel")]])
