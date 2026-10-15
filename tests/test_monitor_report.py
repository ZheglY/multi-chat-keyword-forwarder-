import unittest
from types import SimpleNamespace

from telethon import types, utils
from telethon.extensions import html

from utils.monitor_report import UNAVAILABLE_LINK, build_report, message_link


def channel(username=None, forum=False):
    return types.Channel(5563500182, 'Рабочий чат', types.ChatPhotoEmpty(), None,
                         megagroup=True, username=username, forum=forum)


class MonitorReportTests(unittest.TestCase):
    def report(self, sender=None, chat=None, text='Нужен тендер', keywords=None):
        chat = chat or channel()
        return build_report(chat, sender, text, keywords or ['тендер'],
                            '2026-10-15 12:30:00', utils.get_peer_id(chat), 91798)

    def test_sender_username_links_full_display_name(self):
        sender = types.User(42, first_name='Иван', last_name='Иванов', username='ivan')
        rendered, entities = html.parse(self.report(sender))
        self.assertIn('👤 Отправитель: Иван Иванов\n', rendered)
        links = [entity for entity in entities if isinstance(entity, types.MessageEntityTextUrl)]
        self.assertEqual([entity.url for entity in links], ['https://t.me/ivan'])

    def test_sender_without_username_is_plain_text(self):
        sender = types.User(42, first_name='Иван', last_name='Иванов')
        report = self.report(sender)
        self.assertIn('👤 Отправитель: Иван Иванов\n', report)
        self.assertNotIn('<a ', report)

    def test_last_name_only_uses_telethon_display_name(self):
        self.assertIn('👤 Отправитель: Иванов\n', self.report(types.User(42, last_name='Иванов')))

    def test_channel_sender_and_anonymous_administrator(self):
        sender = channel(username='workgroup')
        self.assertIn('<a href="https://t.me/workgroup">Рабочий чат</a>', self.report(sender))
        sender.username = None
        self.assertIn('👤 Отправитель: Рабочий чат\n', self.report(sender))

    def test_absent_or_empty_sender_is_safe(self):
        for sender in (None, types.User(42)):
            self.assertIn('👤 Отправитель: N/A\n', self.report(sender))

    def test_public_supergroup_and_broadcast_links(self):
        chat = channel(username='workgroup')
        for broadcast in (False, True):
            chat.broadcast = broadcast
            chat.megagroup = not broadcast
            self.assertEqual(message_link(chat, utils.get_peer_id(chat), 91798),
                             'https://t.me/workgroup/91798')

    def test_private_channel_id_is_positive_without_prefix(self):
        chat = channel()
        self.assertEqual(utils.get_peer_id(chat), -1005563500182)
        self.assertEqual(message_link(chat, -1005563500182, 91798),
                         'https://t.me/c/5563500182/91798')

    def test_basic_group_never_gets_channel_link(self):
        chat = types.Chat(5563500182, 'Group', types.ChatPhotoEmpty(), 1, None, 1)
        self.assertEqual(message_link(chat, -5563500182, 91798), UNAVAILABLE_LINK)
        self.assertIn('🔗 Ссылка: ' + UNAVAILABLE_LINK, self.report(chat=chat))
        self.assertNotIn('https://t.me/c/', self.report(chat=chat))

    def test_mismatched_or_missing_peer_data_cannot_invent_link(self):
        for chat_id in (-5563500182, None, -1000000000123):
            self.assertEqual(message_link(channel(), chat_id, 91798), UNAVAILABLE_LINK)

    def test_forum_topic_links_public_private_and_root_reply(self):
        for username in ('workgroup', None):
            chat = channel(username=username, forum=True)
            base = 'https://t.me/workgroup' if username else 'https://t.me/c/5563500182'
            for reply in (
                types.MessageReplyHeader(forum_topic=True, reply_to_top_id=80, reply_to_msg_id=90),
                types.MessageReplyHeader(forum_topic=True, reply_to_msg_id=80),
            ):
                message = SimpleNamespace(reply_to=reply)
                self.assertEqual(message_link(chat, utils.get_peer_id(chat), 91798, message),
                                 base + '/80/91798')

    def test_nonforum_reply_and_missing_topic_keep_direct_link(self):
        chat = channel(username='workgroup', forum=True)
        for reply in (None, types.MessageReplyHeader(forum_topic=False, reply_to_msg_id=90),
                      types.MessageReplyHeader(forum_topic=True)):
            self.assertEqual(message_link(chat, utils.get_peer_id(chat), 91798,
                                          SimpleNamespace(reply_to=reply)),
                             'https://t.me/workgroup/91798')

    def test_html_is_escaped_without_altering_message_or_line_breaks(self):
        chat = channel()
        chat.title = '<Чат> & "тест"'
        sender = types.User(42, first_name='<Иван> & "И"', username='ivan')
        text = '🙂 <b>тендер</b> & "цена"\nвторая строка\n<a href="https://evil.test">ссылка</a>'
        report = self.report(sender, chat, text, ['<тендер>', 'A&B'])
        rendered, entities = html.parse(report)
        self.assertIn('✉️ Сообщение:\n' + text + '\n\n', rendered)
        self.assertIn('💬 Чат: ' + chat.title + '\n', rendered)
        self.assertIn('🔍 Ключевые слова: <тендер>, A&B\n', rendered)
        self.assertIn('👤 Отправитель: <Иван> & "И"\n', rendered)
        self.assertNotIn('<b>тендер</b>', report)
        self.assertEqual(len(entities), 1)  # Only our sender link becomes an entity.
        self.assertEqual(entities[0].url, 'https://t.me/ivan')

    def test_user_id_and_separate_username_fields_are_removed(self):
        report = self.report(types.User(999999, first_name='Иван', username='ivan'))
        self.assertNotIn('User ID', report)
        self.assertNotIn('Username:', report)
        self.assertNotIn('999999', report)


if __name__ == '__main__':
    unittest.main()
