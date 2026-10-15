"""Exercise the existing handler with no config import, disk logs or Telegram."""

from datetime import datetime
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
from telethon import types

from utils.monitor_settings import MonitorSettings
from utils.monitored_chats import MonitoredChats


class MonitorModesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings_path = Path(directory.name) / 'monitor.json'
        self.settings = MonitorSettings(self.settings_path)
        self.client = SimpleNamespace(
            on=Mock(side_effect=lambda event: lambda function: function),
            get_permissions=AsyncMock(return_value=True),
            send_message=AsyncMock(),
        )
        self.keywords = Mock()
        self.keywords.get_keywords.return_value = ['тендер']
        self.keywords.get_ban_words.return_value = ['спам']
        modules = {}
        for name, attributes in (
            ('config.bot_config', {'client': self.client}),
            ('utils.logger', {'get_logger': Mock(return_value=Mock())}),
            ('utils.special_func', {'is_user_allowed': Mock(return_value=True)}),
            ('utils.json_keywords_manager', {'keywords_manager': self.keywords}),
        ):
            module = ModuleType(name)
            module.__dict__.update(attributes)
            modules[name] = module
        source = Path(__file__).resolve().parents[1] / 'handlers/commands/base_handlers.py'
        spec = importlib.util.spec_from_file_location('isolated_base_handlers', source)
        self.handler = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', modules), patch(
            'utils.monitor_settings.MonitorSettings', return_value=self.settings
        ):
            spec.loader.exec_module(self.handler)
        self.sender = types.User(42, first_name='Иван', last_name='Иванов', username='ivan')

    def event(self, chat_id=-1000000000123, text='Новый ТЕНДЕР'):
        return SimpleNamespace(
            chat_id=chat_id, raw_text=text, id=7,
            get_chat=AsyncMock(return_value=types.Channel(
                123, 'Тестовый чат', types.ChatPhotoEmpty(), None, megagroup=True)),
            get_sender=AsyncMock(return_value=self.sender),
        )

    async def test_simple_empty_skips_before_keywords_and_telegram(self):
        event = self.event()
        await self.handler.keyword_monitor(event)
        self.keywords.get_keywords.assert_not_called()
        self.keywords.get_ban_words.assert_not_called()
        event.get_chat.assert_not_awaited()
        self.client.send_message.assert_not_awaited()

    async def test_simple_selected_id_passes_and_other_id_is_ignored(self):
        # Same title/link cannot substitute for the saved numeric ID.
        self.settings.save_chat(-1000000000123, 'Тестовый чат', 't.me/testname')
        await self.handler.keyword_monitor(self.event(-1000000000999))
        self.keywords.get_keywords.assert_not_called()
        await self.handler.keyword_monitor(self.event())
        self.client.send_message.assert_awaited_once()

    async def test_basic_group_numeric_id(self):
        self.settings.save_chat(-77, 'Group')
        await self.handler.keyword_monitor(self.event(-77))
        self.client.send_message.assert_awaited_once()

    async def test_advanced_accepts_unsaved_chat(self):
        self.settings.set_mode('advanced')
        await self.handler.keyword_monitor(self.event())
        self.client.send_message.assert_awaited_once()

    async def test_both_modes_keep_keyword_and_ban_rules(self):
        self.settings.save_chat(-1000000000123)
        for mode in ('simple', 'advanced'):
            self.settings.set_mode(mode)
            for text, expected in (('Без совпадений', 0), ('тендер спам', 0),
                                   ('Новый ТЕНДЕР', 1), ('субтендер', 1), ('', 0), (None, 0)):
                with self.subTest(mode=mode, text=text):
                    self.client.send_message.reset_mock()
                    await self.handler.keyword_monitor(self.event(text=text))
                    self.assertEqual(self.client.send_message.await_count, expected)

    async def test_report_keeps_other_fields_with_new_sender_and_link(self):
        self.settings.set_mode('advanced')
        fixed = datetime(2026, 10, 15, 12, 30)
        with patch.object(self.handler, 'datetime') as clock:
            clock.now.return_value = fixed
            await self.handler.keyword_monitor(self.event())
        self.client.send_message.assert_awaited_once_with(
            entity='me', link_preview=False, parse_mode='html',
            message=(
                '==============================\n'
                '📅 Дата: 2026-10-15 12:30:00\n\n'
                '💬 Чат: Тестовый чат\n'
                '✉️ Сообщение:\nНовый ТЕНДЕР\n\n'
                '🔍 Ключевые слова: тендер\n'
                '👤 Отправитель: <a href="https://t.me/ivan">Иван Иванов</a>\n'
                '🔗 Ссылка: https://t.me/c/123/7\n'
                '=============================='
            ),
        )

    async def test_channel_and_missing_sender_do_not_break_reports(self):
        self.settings.set_mode('advanced')
        channel = types.Channel(123, 'Канал', types.ChatPhotoEmpty(), None)
        for sender, label in ((channel, 'Канал'), (None, 'N/A')):
            event = self.event()
            event.get_sender.return_value = sender
            self.client.send_message.reset_mock()
            await self.handler.keyword_monitor(event)
            self.client.send_message.assert_awaited_once()
            report = self.client.send_message.call_args.kwargs['message']
            self.assertIn(f'👤 Отправитель: {label}\n', report)

    async def test_lost_access_blocks_both_modes_before_words(self):
        self.settings.save_chat(-1000000000123)
        for mode in ('simple', 'advanced'):
            self.settings.set_mode(mode)
            for denied in (False, RuntimeError('lost access')):
                self.client.get_permissions.side_effect = denied if isinstance(denied, Exception) else None
                self.client.get_permissions.return_value = False
                await self.handler.keyword_monitor(self.event())
        self.keywords.get_keywords.assert_not_called()
        self.client.send_message.assert_not_awaited()

    async def test_switch_and_delete_take_effect_without_restart(self):
        self.settings.save_chat(-1000000000123)
        await self.handler.keyword_monitor(self.event())
        self.settings.set_mode('advanced')
        await self.handler.keyword_monitor(self.event(-1000000000999))
        self.settings.set_mode('simple')
        await self.handler.keyword_monitor(self.event(-1000000000999))
        self.handler.monitored_chats.delete_chat(-1000000000123)
        await self.handler.keyword_monitor(self.event())
        self.assertEqual(self.client.send_message.await_count, 2)

    async def test_corrupt_settings_fail_closed_before_words(self):
        self.settings_path.write_bytes(b'broken')
        await self.handler.keyword_monitor(self.event())
        self.keywords.get_keywords.assert_not_called()
        self.client.send_message.assert_not_awaited()
        self.assertEqual(self.settings_path.read_bytes(), b'broken')

    async def test_single_existing_incoming_nonprivate_registration(self):
        self.client.on.assert_called_once()
        builder = self.client.on.call_args.args[0]
        self.assertTrue(builder.incoming)
        self.assertFalse(builder.func(SimpleNamespace(is_private=True)))
        self.assertTrue(builder.func(SimpleNamespace(is_private=False)))

    async def test_scope_rejects_non_numeric_id(self):
        service = MonitoredChats(self.client, self.settings)
        for mode in ('simple', 'advanced'):
            self.settings.set_mode(mode)
            for value in ('-1000000000123', 't.me/testname', None, True):
                self.assertFalse(service.is_chat_allowed(value))


if __name__ == '__main__':
    unittest.main()
