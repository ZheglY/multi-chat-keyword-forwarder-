from aiogram import Router, F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from states.all_states import FiltersStates
from utils.logger import get_logger
from utils.special_func import is_user_allowed
from utils.json_keywords_manager import keywords_manager

logger = get_logger(__name__)
filters_router = Router()



@filters_router.message(Command("ban"))
async def show_ban_words(message: Message, state: FSMContext):
    """Обработчик команды /ban"""
    if message.chat.type != ChatType.PRIVATE:
        return

    if not is_user_allowed(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    current_ban_words = keywords_manager.get_ban_words()
    text = (
            f"🔍 Текущие бан слова:\n {current_ban_words}" 
            '\n\nВведите новые слова для поиска через пробел.\n'
            'Пример: BANK рассылка СПАМ'
    )

    await state.set_state(FiltersStates.ban_words)
    await message.answer(text)
    logger.info(f"Пользователь {message.from_user.id} запросил /ban")


@filters_router.message(FiltersStates.ban_words)
async def save_ban_words(message: Message, state: FSMContext):
    """Сохранение новых бан слов"""
    try:
        ban_words = [word.strip() for word in message.text.split() if word.strip()]

        if not ban_words:
            await message.answer("❌ Список бан-слов не может быть пустым!")
            return

        keywords_manager.set_ban_words(ban_words)

        updated_ban_words = keywords_manager.get_ban_words()

        text = (f'✅ Бан-слова сохранены!\n'
                f'Новый список: {" ".join(updated_ban_words)}\n\n'
                f'Теперь сообщения с этими словами будут блокироваться.')

        await state.clear()
        await message.answer(text)
        logger.info(f"Пользователь {message.from_user.id} установил бан-слова: {updated_ban_words}")

    except Exception as e:
        logger.error(f"Ошибка при сохранении бан-слов: {e}")
        await message.answer("❌ Произошла ошибка при сохранении бан-слов")


# ------------------------------------------------------------------------------------------------


@filters_router.message(Command("filters"))
async def show_filters(message: Message, state: FSMContext):
    """Обработчик команды /filters"""
    if message.chat.type != ChatType.PRIVATE:
        return

    if not is_user_allowed(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    await prompt_filters(message, state)


async def prompt_filters(message: Message, state: FSMContext):
    """Shared prompt; entry-point authorization is handled by caller/middleware."""
    current_filters = keywords_manager.get_keywords()

    text = (
            f"🔍 Текущие ключевые слова: {current_filters}\n"
            '\n\nВведите новые слова для поиска через пробел.\n'
            'Пример: Youtube reels видеомонтаж'
    )

    await state.set_state(FiltersStates.filter_words)
    await message.answer(text)
    logger.info(f"Пользователь {message.from_user.id} запросил /filters")


@filters_router.message(FiltersStates.filter_words)
async def save_filters(message: Message, state: FSMContext):
    """Сохранение новых фильтров"""
    try:
        new_filters = [word.strip() for word in message.text.split() if word.strip()]

        if not new_filters:
            await message.answer("❌ Список фильтров не может быть пустым!")
            return

        keywords_manager.set_keywords(new_filters)
        updated_filters = keywords_manager.get_keywords()

        text = (f'✅ Фильтры сохранены!\n'
                f'Новый список: {" ".join(updated_filters)}\n\n'
                f'Продолжаю искать сообщения по фильтрам...')

        await state.clear()
        await message.answer(text)
        logger.info(f"Пользователь {message.from_user.id} изменил фильтры на: {updated_filters}")

    except Exception as e:
        logger.error(f"Ошибка при сохранении фильтров: {e}")
        await message.answer("❌ Произошла ошибка при сохранении фильтров")
