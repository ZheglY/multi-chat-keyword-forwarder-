"""Notification presentation only; no Telegram requests or monitoring decisions."""

from html import escape

from telethon import types, utils


UNAVAILABLE_LINK = 'недоступна для этого типа чата'


def message_link(chat, chat_id, message_id, message=None):
    """Build a direct message link; basic groups have no supported t.me/c link."""
    if type(chat_id) is not int or type(message_id) is not int or message_id <= 0:
        return UNAVAILABLE_LINK
    channel_id, peer_type = utils.resolve_id(chat_id)
    if (peer_type is not types.PeerChannel or channel_id <= 0
            or not isinstance(chat, types.Channel) or chat.id != channel_id):
        return UNAVAILABLE_LINK
    username = getattr(chat, 'username', None)
    base = f'https://t.me/{username}' if username else f'https://t.me/c/{channel_id}'
    reply = getattr(message, 'reply_to', None)
    if getattr(chat, 'forum', False) and getattr(reply, 'forum_topic', False):
        topic_id = getattr(reply, 'reply_to_top_id', None) or getattr(reply, 'reply_to_msg_id', None)
        if type(topic_id) is int and topic_id > 0:
            return f'{base}/{topic_id}/{message_id}'
    return f'{base}/{message_id}'


def build_report(chat, sender, text, keywords, date, chat_id, message_id, message=None):
    """Return Telegram HTML with original message text preserved when rendered."""
    sender_name = escape(utils.get_display_name(sender) or 'N/A')
    username = getattr(sender, 'username', None)
    if username:
        url = escape(f'https://t.me/{username}', quote=True)
        sender_name = f'<a href="{url}">{sender_name}</a>'
    link = message_link(chat, chat_id, message_id, message)
    return (
        '==============================\n'
        f'📅 Дата: {escape(date)}\n\n'
        f"💬 Чат: {escape(getattr(chat, 'title', 'Private Chat'))}\n"
        f'✉️ Сообщение:\n{escape(text)}\n\n'
        f"🔍 Ключевые слова: {escape(', '.join(keywords))}\n"
        f'👤 Отправитель: {sender_name}\n'
        f'🔗 Ссылка: {escape(link)}\n'
        '=============================='
    )
