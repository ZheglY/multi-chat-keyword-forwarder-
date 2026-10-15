from datetime import datetime
from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.types import Message
from telethon import events

from utils.json_keywords_manager import keywords_manager
from utils.logger import get_logger
from utils.special_func import is_user_allowed
from config.bot_config import client
from utils.monitor_settings import MonitorSettings
from utils.monitored_chats import MonitoredChats, MonitoredChatError
from utils.monitor_keyboard import monitor_menu
from utils.monitor_report import build_report


logger = get_logger(__name__)
base_handlers = Router()
monitor_settings = MonitorSettings()
monitored_chats = MonitoredChats(client, monitor_settings)



@base_handlers.message(CommandStart())
async def start_command(message: Message):
    """Обработчик команды /start"""
    if message.chat.type != ChatType.PRIVATE:
        logger.warning(f"Попытка вызвать /start в чате {message.chat.id}")
        return

    if not is_user_allowed(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    try:
        mode_text = f"Текущий режим: {monitored_chats.get_mode()}"
    except MonitoredChatError:
        mode_text = "Настройки недоступны. Мониторинг приостановлен."

    await message.answer(
        "👋 Привет! Я бот для мониторинга чатов.\n"
        "Доступные команды:\n"
        "/filters — показать и изменить ключевые слова\n"
        "/ban — показать и изменить бан слова\n\n"
        "Я автоматически ищу сообщения с ключевыми словами и присылаю их тебе.\n\n"
        + mode_text,
        reply_markup=monitor_menu(),
    )
    logger.info(f"Пользователь {message.from_user.id} запустил /start")


@client.on(events.NewMessage(incoming=True, func=lambda e: not e.is_private))
async def keyword_monitor(event):
    """Мониторинг сообщений в чатах на ключевые слова"""

    try:
        if not monitored_chats.is_chat_allowed(event.chat_id):
            return
    except MonitoredChatError as e:
        logger.error(f"Ошибка настроек мониторинга: {e}")
        return

    try:
        chat = await event.get_chat()
        my_participant = await client.get_permissions(chat, 'me')
        if not my_participant:
            return
    except Exception as e:
        logger.debug(e)
        return

    try:
        logger.debug(f"Получено сообщение: {(event.raw_text or '')[:50]}...")

        text = event.raw_text.lower() if event.raw_text else ""

        filters = keywords_manager.get_keywords()
        ban_words = keywords_manager.get_ban_words()

        found_ban_words = [word for word in ban_words if word.lower() in text]
        if found_ban_words:
            return

        found_keywords = [word for word in filters if word.lower() in text]
        if not found_keywords:
            return


        if not found_keywords:
            return

        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        chat = await event.get_chat()
        sender = await event.get_sender()

        chat_id = event.chat_id
        report = build_report(
            chat, sender, event.raw_text, found_keywords, date, chat_id, event.id,
            getattr(event, 'message', None),
        )


        await client.send_message(
            entity='me',
            message=report,
            parse_mode='html',
            link_preview=False
        )

        logger.info(f"Найдено ключевое слово в чате {chat_id}")

    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)



