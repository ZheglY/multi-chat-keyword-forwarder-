"""Route real Aiogram updates with a fake Bot session and Telethon client."""

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import (CallbackQuery, Chat, InlineKeyboardMarkup, Message, MessageEntity,
                           ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, User)
from telethon import errors, types, utils

from utils.monitor_settings import MonitorSettings
from utils.monitored_chats import MonitoredChats


OWNER = 42


class OfflineSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.requests = []
        self.reply_keyboard = None

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, SendMessage):
            if isinstance(method.reply_markup, ReplyKeyboardMarkup):
                self.reply_keyboard = method.reply_markup
            elif isinstance(method.reply_markup, ReplyKeyboardRemove):
                self.reply_keyboard = None
            return Message(message_id=len(self.requests), date=datetime.now(timezone.utc),
                           chat=Chat(id=int(method.chat_id), type='private'),
                           from_user=User(id=bot.id, is_bot=True, first_name='Bot'),
                           text=method.text, reply_markup=(method.reply_markup if isinstance(
                               method.reply_markup, InlineKeyboardMarkup) else None))
        if isinstance(method, AnswerCallbackQuery):
            return True
        raise AssertionError(f'Unexpected Telegram API operation: {type(method)}')

    async def stream_content(self, *args, **kwargs):
        raise AssertionError('No network permitted')
        yield


class MonitorInterfaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'settings.json'
        self.settings = MonitorSettings(self.path)
        self.telethon = SimpleNamespace(
            on=Mock(side_effect=lambda event: lambda function: function),
            get_entity=AsyncMock(return_value=types.Channel(
                123, 'Test channel', types.ChatPhotoEmpty(), None, left=False, broadcast=True)),
            get_permissions=AsyncMock(return_value=SimpleNamespace(has_left=False)),
            get_messages=AsyncMock(return_value=[]),
            get_dialogs=AsyncMock(return_value=[]),
        )
        self.keywords = Mock()
        self.keywords.get_keywords.return_value = ['old']
        self.keywords.get_ban_words.return_value = ['spam']
        self.keywords.set_keywords.side_effect = lambda words: setattr(
            self.keywords.get_keywords, 'return_value', words)
        self.keywords.set_ban_words.side_effect = lambda words: setattr(
            self.keywords.get_ban_words, 'return_value', words)
        self.join = Mock(return_value=1)
        replacements = {}
        for name, attrs in (
            ('config.bot_config', {'client': self.telethon, 'BOT_TOKEN': '123456:offline-token',
                                   'ALLOWED_USERS': [OWNER]}),
            ('utils.logger', {'get_logger': Mock(return_value=Mock())}),
            ('utils.json_keywords_manager', {'keywords_manager': self.keywords}),
            ('utils.join_groups', {'join_groups': self.join}),
        ):
            module = ModuleType(name)
            module.__dict__.update(attrs)
            replacements[name] = module
        root = Path(__file__).resolve().parents[1]
        # Load real routers in isolation, never config.bot_config or Telethon login.
        with patch.dict('sys.modules', replacements), patch(
            'utils.monitor_settings.MonitorSettings', return_value=self.settings
        ):
            import sys
            for name in ('utils.special_func', 'states.all_states',
                         'handlers.commands.base_handlers',
                         'handlers.custom_handlers.custom_commands',
                         'handlers.custom_handlers.join_handlers',
                         'handlers.custom_handlers.monitor_handlers', 'handlers.access'):
                spec = importlib.util.spec_from_file_location(name, root / (name.replace('.', '/') + '.py'))
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                spec.loader.exec_module(module)
            spec = importlib.util.spec_from_file_location('offline_main', root / 'main.py')
            self.app = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.app)
        self.bot = self.app.bot
        self.session = OfflineSession()
        self.bot.session = self.session
        self.addAsyncCleanup(self.app.dp.storage.close)
        self.counter = 0

    async def send(self, text=None, user_id=OWNER, chat_type='private'):
        self.counter += 1
        entities = None
        if text and text.startswith('/'):
            entities = [MessageEntity(type='bot_command', offset=0, length=len(text.split()[0]))]
        message = Message(message_id=self.counter, date=datetime.now(timezone.utc),
                          chat=Chat(id=user_id, type=chat_type),
                          from_user=User(id=user_id, is_bot=False, first_name='Tester'),
                          text=text, entities=entities)
        await self.app.dp.feed_update(self.bot, Update(update_id=self.counter, message=message))

    async def click(self, data, user_id=OWNER, chat_type='private'):
        self.counter += 1
        message = Message(message_id=1, date=datetime.now(timezone.utc),
                          chat=Chat(id=user_id, type=chat_type),
                          from_user=User(id=self.bot.id, is_bot=True, first_name='Bot'), text='menu')
        callback = CallbackQuery(id=str(self.counter), from_user=User(
            id=user_id, is_bot=False, first_name='Tester'), chat_instance='test', message=message, data=data)
        await self.app.dp.feed_update(self.bot, Update(update_id=self.counter, callback_query=callback))

    def state(self, user_id=OWNER):
        return self.app.dp.fsm.get_context(bot=self.bot, chat_id=user_id, user_id=user_id)

    def answers(self):
        return [request for request in self.session.requests if isinstance(request, SendMessage)]

    async def test_start_has_requested_menu_and_current_mode(self):
        await self.send('/start')
        answer = self.answers()[-1]
        self.assertIn('simple', answer.text)
        self.assertIsInstance(answer.reply_markup, ReplyKeyboardMarkup)
        labels = [[button.text for button in row] for row in answer.reply_markup.keyboard]
        self.assertEqual(labels, [['➕ Добавить чат', '📋 Мои чаты'], ['🔎 Фильтры'],
                                  ['⚙️ Продвинутые настройки']])
        self.assertTrue(answer.reply_markup.resize_keyboard)
        self.assertTrue(answer.reply_markup.is_persistent)
        self.assertFalse(answer.reply_markup.one_time_keyboard)

    async def test_add_link_list_delete_through_dispatcher(self):
        await self.click('monitor:add')
        self.assertEqual(await self.state().get_state(), 'MonitorStates:chat_link')
        await self.send('https://t.me/testname')
        self.assertIsNone(await self.state().get_state())
        record = self.settings.get_chats()[0]
        self.assertEqual(record['id'], -1000000000123)
        await self.click('monitor:list:0')
        answer = self.answers()[-1]
        self.assertIn('Test channel', answer.text)
        self.assertIn('monitor:delete:-1000000000123', str(answer.reply_markup))
        self.telethon.get_entity.reset_mock()
        await self.click('monitor:delete:-1000000000123')
        self.assertEqual(self.settings.get_chats(), [])
        self.telethon.get_entity.assert_not_awaited()

    async def test_bad_link_and_nontext_keep_input_then_cancel(self):
        await self.click('monitor:add')
        await self.send('not-a-link')
        self.assertEqual(await self.state().get_state(), 'MonitorStates:chat_link')
        await self.send()
        self.assertEqual(await self.state().get_state(), 'MonitorStates:chat_link')
        await self.click('monitor:cancel')
        self.assertIsNone(await self.state().get_state())
        self.telethon.get_entity.assert_not_awaited()
        self.assertEqual(self.settings.get_chats(), [])

    async def test_switch_modes_preserves_list_and_updates_monitor_scope(self):
        self.settings.save_chat(-77, 'Saved', 't.me/savedchat')
        await self.click('monitor:settings')
        self.assertIn('simple', self.answers()[-1].text)
        service = MonitoredChats(self.telethon, self.settings)
        for mode in ('advanced', 'simple'):
            await self.click('monitor:mode:' + mode)
            self.assertEqual(MonitorSettings(self.path).get_mode(), mode)
            self.assertIn('Текущий режим: ' + mode, self.answers()[-1].text)
            self.assertIsNotNone(self.settings.get_chat(-77))
            self.assertEqual(service.is_chat_allowed(-99), mode == 'advanced')

    async def test_filter_button_and_commands_escape_other_states(self):
        await self.click('monitor:add')
        await self.click('monitor:filters')
        self.assertEqual(await self.state().get_state(), 'FiltersStates:filter_words')
        await self.send('тендер закупка')
        self.keywords.set_keywords.assert_called_once_with(['тендер', 'закупка'])
        self.assertIsNone(await self.state().get_state())
        await self.click('monitor:add')
        await self.send('/ban')
        self.assertEqual(await self.state().get_state(), 'FiltersStates:ban_words')
        await self.send('casino spam')
        self.keywords.set_ban_words.assert_called_once_with(['casino', 'spam'])
        await self.click('monitor:add')
        await self.send('/filters')
        self.assertEqual(await self.state().get_state(), 'FiltersStates:filter_words')
        await self.send('/join')
        self.assertEqual(await self.state().get_state(), 'JoinStates:join')
        await self.send('/filters')
        self.assertEqual(await self.state().get_state(), 'FiltersStates:filter_words')
        await self.send('/start')
        self.assertIsNone(await self.state().get_state())
        self.join.assert_not_called()

    async def test_cancel_command_and_menu_escape_join_and_filter_states(self):
        for command in ('/join', '/filters', '/ban'):
            await self.send(command)
            self.assertIsNotNone(await self.state().get_state())
            await self.send('/cancel')
            self.assertIsNone(await self.state().get_state())
        await self.send('/join')
        await self.click('monitor:list:0')
        self.assertIsNone(await self.state().get_state())
        self.join.assert_not_called()

    async def test_outsider_commands_callbacks_and_fsm_input_blocked(self):
        outsider = 999
        for command in ('/start', '/filters', '/ban', '/join', '/cancel'):
            await self.send(command, user_id=outsider)
            self.assertEqual(self.answers()[-1].text, '⛔ Доступ запрещён.')
        for action in ('monitor:add', 'monitor:list:0', 'monitor:filters', 'monitor:settings',
                       'monitor:mode:advanced', 'monitor:delete:-77', 'monitor:cancel'):
            await self.click(action, user_id=outsider)
            last = self.session.requests[-1]
            self.assertIsInstance(last, AnswerCallbackQuery)
            self.assertTrue(last.show_alert)
        for state in ('MonitorStates:chat_link', 'FiltersStates:filter_words',
                      'FiltersStates:ban_words', 'JoinStates:join'):
            await self.state(outsider).set_state(state)
            await self.send('https://t.me/testname', user_id=outsider)
            self.assertEqual(await self.state(outsider).get_state(), state)
        self.telethon.get_entity.assert_not_awaited()
        self.keywords.set_keywords.assert_not_called()
        self.keywords.set_ban_words.assert_not_called()
        self.join.assert_not_called()
        self.assertFalse(self.path.exists())

    async def test_owner_group_events_cannot_change_settings(self):
        await self.send('/start', chat_type='group')
        await self.click('monitor:mode:advanced', chat_type='group')
        self.assertEqual(self.settings.get_mode(), 'simple')
        self.assertEqual(self.answers(), [])

    async def test_expired_buttons_and_storage_errors_are_reported(self):
        await self.click('monitor:delete:-77')
        self.assertIn('не найден', self.answers()[-1].text)
        await self.click('monitor:delete:bad')
        self.assertIn('Некорректная', self.answers()[-1].text)
        await self.click('monitor:mode:invalid')
        self.assertEqual(self.settings.get_mode(), 'simple')
        self.path.write_bytes(b'broken')
        await self.click('monitor:settings')
        self.assertIn('хранилища', self.answers()[-1].text)
        await self.send('/start')
        self.assertIn('приостановлен', self.answers()[-1].text)
        self.assertEqual(self.path.read_bytes(), b'broken')

    async def test_paginated_chat_list(self):
        for index in range(10):
            self.settings.save_chat(-index - 1, f'Chat {index}', 't.me/testname')
        await self.click('monitor:list:0')
        markup = str(self.answers()[-1].reply_markup)
        self.assertIn('monitor:list:1', markup)
        self.assertEqual(markup.count('monitor:delete:'), 8)
        await self.click('monitor:list:1')
        self.assertEqual(str(self.answers()[-1].reply_markup).count('monitor:delete:'), 2)

    async def test_add_access_errors_keep_input_without_saving(self):
        await self.click('monitor:add')
        self.telethon.get_entity.side_effect = errors.ChannelPrivateError(None)
        await self.send('t.me/testname')
        self.assertIn('Нет доступа', self.answers()[-1].text)
        self.assertEqual(await self.state().get_state(), 'MonitorStates:chat_link')
        self.telethon.get_entity.side_effect = errors.FloodWaitError(None, 12)
        await self.send('t.me/testname')
        self.assertIn('12 с.', self.answers()[-1].text)
        self.assertEqual(self.settings.get_chats(), [])

    async def test_join_still_routes_to_existing_service(self):
        await self.send('/join')
        await self.send('https://t.me/testname')
        self.join.assert_called_once_with(['testname'])
        self.assertIsNone(await self.state().get_state())
        self.assertEqual(self.settings.get_chats(), [])
        self.telethon.on.assert_called_once()

    def id_dialogs(self, *entities):
        self.telethon.get_dialogs.return_value = [
            SimpleNamespace(entity=entity, id=utils.get_peer_id(entity)) for entity in entities
        ]

    async def begin_ambiguous_choice(self):
        group = types.Chat(123, 'Group', types.ChatPhotoEmpty(), 1, None, 1)
        self.id_dialogs(group, self.telethon.get_entity.return_value)
        await self.click('monitor:add')
        await self.send('123')
        self.assertEqual(self.settings.get_chats(), [])
        answer = self.answers()[-1]
        self.assertIn('Выберите', answer.text)
        return [row[0].callback_data for row in answer.reply_markup.inline_keyboard
                if row[0].callback_data.startswith('monitor:choose:')]

    async def test_numeric_input_and_requested_prompt(self):
        self.id_dialogs(self.telethon.get_entity.return_value)
        await self.click('monitor:add')
        self.assertEqual(self.answers()[-1].text,
                         'Отправьте ссылку или ID Telegram-чата. Можно вводить ID '
                         'без -100 и минуса — я определю нужный формат автоматически')
        await self.send('123')
        self.assertEqual(self.settings.get_chats()[0]['id'], -1000000000123)
        self.assertIsNone(await self.state().get_state())

    async def test_ambiguous_choice_saves_only_selected_chat(self):
        buttons = await self.begin_ambiguous_choice()
        self.assertEqual(len(buttons), 2)
        await self.click(buttons[1])
        self.assertEqual(self.settings.get_chats()[0]['id'], -1000000000123)
        self.assertIsNone(await self.state().get_state())
        self.assertEqual(self.telethon.get_dialogs.await_count, 2)

    async def test_cancelled_or_superseded_choices_are_rejected(self):
        buttons = await self.begin_ambiguous_choice()
        await self.click('monitor:cancel')
        await self.click(buttons[0])
        self.assertEqual(self.settings.get_chats(), [])
        self.assertIn('устарел', self.answers()[-1].text)
        buttons = await self.begin_ambiguous_choice()
        await self.send('invalid')
        await self.click(buttons[0])
        self.assertEqual(self.settings.get_chats(), [])

    async def test_choice_rechecks_current_dialog_and_access(self):
        buttons = await self.begin_ambiguous_choice()
        # Basic group disappeared; channel with same raw ID must not replace it.
        self.id_dialogs(self.telethon.get_entity.return_value)
        await self.click(buttons[0])
        self.assertEqual(self.settings.get_chats(), [])
        self.assertIn('не найден', self.answers()[-1].text)
        self.telethon.get_messages.side_effect = errors.ChannelPrivateError(None)
        await self.click(buttons[1])
        self.assertEqual(self.settings.get_chats(), [])
        self.assertIn('Нет доступа', self.answers()[-1].text)

    async def test_unknown_id_has_clear_error_and_keeps_input(self):
        await self.click('monitor:add')
        await self.send('999999')
        self.assertIn('не найден среди доступных диалогов', self.answers()[-1].text)
        self.assertEqual(await self.state().get_state(), 'MonitorStates:chat_link')
        self.assertEqual(self.settings.get_chats(), [])

    async def test_choice_cannot_be_forged_or_used_by_outsider(self):
        buttons = await self.begin_ambiguous_choice()
        await self.click(buttons[0], user_id=999)
        self.assertTrue(self.session.requests[-1].show_alert)
        await self.click(buttons[0].rsplit(':', 1)[0] + ':-999')
        self.assertIn('устарел', self.answers()[-1].text)
        self.assertEqual(self.settings.get_chats(), [])

    async def test_reply_menu_workflow_keeps_keyboard_available(self):
        await self.send('/start')
        self.assertIsNotNone(self.session.reply_keyboard)
        before = len(self.answers())
        await self.send('➕ Добавить чат')
        self.assertEqual(len(self.answers()), before + 1)  # Only the input prompt.
        self.assertEqual(await self.state().get_state(), 'MonitorStates:chat_link')
        self.assertIsNotNone(self.session.reply_keyboard)
        await self.send('https://t.me/testname')
        self.assertEqual(len(self.settings.get_chats()), 1)
        self.assertIsNotNone(self.session.reply_keyboard)
        await self.send('📋 Мои чаты')
        self.assertIsInstance(self.answers()[-1].reply_markup, InlineKeyboardMarkup)
        await self.click('monitor:delete:-1000000000123')
        self.assertEqual(self.settings.get_chats(), [])
        self.assertIsNotNone(self.session.reply_keyboard)
        await self.send('🔎 Фильтры')
        await self.send('тендер закупка')
        self.keywords.set_keywords.assert_called_once_with(['тендер', 'закупка'])
        self.assertIsNotNone(self.session.reply_keyboard)
        await self.send('⚙️ Продвинутые настройки')
        self.assertIsInstance(self.answers()[-1].reply_markup, InlineKeyboardMarkup)
        await self.click('monitor:mode:advanced')
        self.assertEqual(self.settings.get_mode(), 'advanced')
        self.assertIsNotNone(self.session.reply_keyboard)
        self.assertFalse(any(isinstance(request.reply_markup, ReplyKeyboardRemove)
                             for request in self.answers()))

    async def test_reply_menu_switches_all_pending_fsm_scenarios(self):
        targets = [('➕ Добавить чат', 'MonitorStates:chat_link'), ('📋 Мои чаты', None),
                   ('🔎 Фильтры', 'FiltersStates:filter_words'),
                   ('⚙️ Продвинутые настройки', None)]
        for pending in ('MonitorStates:chat_link', 'FiltersStates:filter_words',
                        'FiltersStates:ban_words', 'JoinStates:join'):
            for text, expected in targets:
                with self.subTest(pending=pending, text=text):
                    await self.state().set_state(pending)
                    await self.state().set_data({'choice_token': 'stale', 'choice_ids': ['-77']})
                    before = len(self.answers())
                    await self.send(text)
                    self.assertEqual(await self.state().get_state(), expected)
                    self.assertEqual(await self.state().get_data(), {})
                    self.assertEqual(len(self.answers()), before + 1)
        self.telethon.get_entity.assert_not_awaited()
        self.keywords.set_keywords.assert_not_called()
        self.keywords.set_ban_words.assert_not_called()
        self.join.assert_not_called()

    async def test_reply_menu_respects_access_checks(self):
        for text in ('➕ Добавить чат', '📋 Мои чаты', '🔎 Фильтры', '⚙️ Продвинутые настройки'):
            await self.state(999).set_state('MonitorStates:chat_link')
            await self.send(text, user_id=999)
            self.assertEqual(self.answers()[-1].text, '⛔ Доступ запрещён.')
            self.assertIsNone(self.session.reply_keyboard)
            self.assertEqual(await self.state(999).get_state(), 'MonitorStates:chat_link')
        self.assertFalse(self.path.exists())
        self.telethon.get_entity.assert_not_awaited()

    async def test_reply_add_accepts_numeric_id_and_old_callback_menu(self):
        self.id_dialogs(self.telethon.get_entity.return_value)
        await self.send('/start')
        await self.send('➕ Добавить чат')
        await self.send('123')
        self.assertEqual(self.settings.get_chats()[0]['id'], -1000000000123)
        await self.click('monitor:menu')
        self.assertIsInstance(self.answers()[-1].reply_markup, ReplyKeyboardMarkup)
        await self.click('monitor:add')
        await self.click('monitor:cancel')
        self.assertIsNone(await self.state().get_state())
        self.assertIsNotNone(self.session.reply_keyboard)


if __name__ == '__main__':
    unittest.main()
