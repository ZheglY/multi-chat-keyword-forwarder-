"""Guard every incoming message/callback before handlers, including FSM input."""

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery

from utils.special_func import is_user_allowed


class OwnerAccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        callback = isinstance(event, CallbackQuery)
        message = event.message if callback else event
        user = event.from_user
        if (not user or not is_user_allowed(user.id) or message is None
                or message.chat.type != ChatType.PRIVATE):
            if callback:
                await event.answer("⛔ Доступ запрещён.", show_alert=True)
            elif message is not None and message.chat.type == ChatType.PRIVATE:
                await message.answer("⛔ Доступ запрещён.")
            return
        # Commands must escape any pending link/filter/join input. Refresh the
        # StateFilter snapshot as well as storage before child routers run.
        if not callback and event.text and event.text.startswith('/'):
            state = data.get('state')
            if state is not None:
                await state.clear()
                data['raw_state'] = None
        return await handler(event, data)
