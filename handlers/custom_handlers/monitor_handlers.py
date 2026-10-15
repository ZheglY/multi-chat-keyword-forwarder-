from aiogram import F, Router
from secrets import token_hex
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from handlers.commands.base_handlers import monitored_chats
from handlers.custom_handlers.custom_commands import prompt_filters
from states.all_states import MonitorStates
from utils.monitor_keyboard import MAIN_MENU_ACTIONS, cancel_keyboard, keyboard, monitor_menu
from utils.monitored_chats import MonitoredChatError


monitor_router = Router()
PAGE_SIZE = 8
ERROR_MESSAGES = {
    'invalid_link': 'Пришлите ссылку t.me/name, t.me/+… или числовой ID чата.',
    'invalid_id': 'Пришлите числовой ID Telegram-чата.',
    'id_not_found': 'Чат с этим ID не найден среди доступных диалогов аккаунта. '
                    'Проверьте ID и наличие доступа или отправьте ссылку.',
    'invalid_invite': 'Приглашение недействительно или истекло.',
    'access_denied': 'Нет доступа. Сначала вступите в чат этим аккаунтом через Telegram.',
    'invalid_chat_type': 'Можно добавить только группу или канал.',
    'not_found': 'Чат не найден.',
    'unauthorized': 'Сессия Telegram не авторизована.',
    'unavailable': 'Telegram недоступен. Попробуйте позже.',
    'storage_error': 'Ошибка хранилища. Существующие данные не перезаписаны.',
    'invalid_mode': 'Неизвестный режим.',
}


def error_text(error):
    if error.code == 'rate_limited':
        return f'Telegram ограничил запросы. Повторите через {error.retry_after} с.'
    return ERROR_MESSAGES.get(error.code, 'Не удалось выполнить запрос к Telegram.')


async def show_menu(message):
    await message.answer(f'Текущий режим: {monitored_chats.get_mode()}', reply_markup=monitor_menu())


async def show_chats(message, page=0):
    chats = monitored_chats.get_chats()
    mode = monitored_chats.get_mode()
    page = min(max(page, 0), max((len(chats) - 1) // PAGE_SIZE, 0))
    selected = chats[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    text = f'Текущий режим: {mode}\nВыбранных чатов: {len(chats)}'
    if not chats:
        text += '\nСписок пуст. В simple сообщения не пересылаются.'
    if mode == 'advanced':
        text += '\nСейчас мониторятся все доступные группы и каналы.'
    rows = []
    for chat in selected:
        title = chat['title'][:100]
        text += f"\n\n{title} · {chat['id']}\n{chat['link'][:180]}"
        rows.append([(f"🗑 {title[:40] or chat['id']}", f"monitor:delete:{chat['id']}")])
    navigation = []
    if page:
        navigation.append(('←', f'monitor:list:{page - 1}'))
    if (page + 1) * PAGE_SIZE < len(chats):
        navigation.append(('→', f'monitor:list:{page + 1}'))
    if navigation:
        rows.append(navigation)
    rows.append([('Меню', 'monitor:menu')])
    # User-supplied metadata must never become Telegram markup.
    await message.answer(text, reply_markup=keyboard(rows), parse_mode=None)


@monitor_router.message(Command('cancel'))
async def cancel_input(message: Message, state: FSMContext):
    await state.clear()
    try:
        await show_menu(message)
    except MonitoredChatError as error:
        await message.answer(error_text(error), reply_markup=monitor_menu())


@monitor_router.callback_query(F.data.startswith('monitor:choose:'))
async def choose_chat(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    parts = callback.data.split(':')
    if (await state.get_state() != MonitorStates.chat_link.state or len(parts) != 4
            or parts[2] != data.get('choice_token')
            or parts[3] not in data.get('choice_ids', [])):
        await callback.message.answer('Выбор устарел. Отправьте ссылку или ID заново.')
        return
    try:
        # Canonical IDs are re-resolved against current dialogs and access is
        # checked again, rather than trusting callback metadata or cached entities.
        chat = await monitored_chats.add_id(int(parts[3]), exact_only=True)
    except MonitoredChatError as error:
        await callback.message.answer(error_text(error), reply_markup=cancel_keyboard())
        return
    await state.clear()
    await confirm_chat(callback.message, chat)


@monitor_router.callback_query(F.data.startswith('monitor:'))
async def monitor_action(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await perform_action(callback.message, state, callback.data)


@monitor_router.message(F.text.in_(MAIN_MENU_ACTIONS))
async def main_menu_action(message: Message, state: FSMContext):
    # Registered before link input and the filter/join routers, so menu text
    # switches the scenario instead of being saved as a link or keyword.
    await perform_action(message, state, MAIN_MENU_ACTIONS[message.text])


async def perform_action(message: Message, state: FSMContext, action: str):
    await state.clear()
    try:
        if action == 'monitor:add':
            await state.set_state(MonitorStates.chat_link)
            await message.answer('Отправьте ссылку или ID Telegram-чата. Можно вводить ID '
                                 'без -100 и минуса — я определю нужный формат автоматически',
                                 reply_markup=cancel_keyboard())
        elif action in ('monitor:cancel', 'monitor:menu'):
            await show_menu(message)
        elif action == 'monitor:filters':
            await prompt_filters(message, state)
        elif action == 'monitor:settings' or action.startswith('monitor:mode:'):
            if action.startswith('monitor:mode:'):
                monitored_chats.set_mode(action.removeprefix('monitor:mode:'))
            mode = monitored_chats.get_mode()
            await message.answer(
                f'Текущий режим: {mode}\n'
                'simple — только выбранные чаты.\n'
                'advanced — все доступные группы и каналы.\n'
                'Список выбранных чатов сохраняется при переключении.',
                reply_markup=keyboard([
                    [('simple', 'monitor:mode:simple'), ('advanced', 'monitor:mode:advanced')],
                    [('Меню', 'monitor:menu')],
                ]),
            )
        elif action.startswith('monitor:list:'):
            await show_chats(message, int(action.removeprefix('monitor:list:')))
        elif action.startswith('monitor:delete:'):
            monitored_chats.delete_chat(int(action.removeprefix('monitor:delete:')))
            await message.answer('Чат удалён из выбранного списка.')
            await show_chats(message)
        else:
            await message.answer('Неизвестное действие. Откройте /start.')
    except MonitoredChatError as error:
        await message.answer(error_text(error), reply_markup=monitor_menu())
    except ValueError:
        await message.answer('Некорректная кнопка. Откройте /start.')


@monitor_router.message(MonitorStates.chat_link)
async def receive_link(message: Message, state: FSMContext):
    await state.set_data({})
    if not message.text:
        await message.answer('Пришлите ссылку или ID текстом или отмените ввод.', reply_markup=cancel_keyboard())
        return
    try:
        chat = await monitored_chats.add_input(message.text)
    except MonitoredChatError as error:
        if error.code == 'ambiguous_id':
            token = token_hex(4)
            await state.set_data({'choice_token': token,
                                  'choice_ids': [str(chat['id']) for chat in error.candidates]})
            rows = [[(f"{chat['title'][:35]} · {chat['id']}",
                      f"monitor:choose:{token}:{chat['id']}")] for chat in error.candidates]
            rows.append([('Отмена', 'monitor:cancel')])
            await message.answer('Найдено несколько чатов с этим ID. Выберите нужный:',
                                 reply_markup=keyboard(rows))
            return
        await message.answer(error_text(error), reply_markup=cancel_keyboard())
        return
    await state.clear()
    await confirm_chat(message, chat)


async def confirm_chat(message, chat):
    await message.answer(f"✅ Чат в списке: {chat['title'][:100]} ({chat['id']})",
                         reply_markup=monitor_menu(), parse_mode=None)
