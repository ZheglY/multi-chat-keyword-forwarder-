from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from telethon import errors, types, utils
from telethon.tl.functions.messages import CheckChatInviteRequest

from utils.monitor_settings import MonitorSettings
from utils.monitored_chats import MonitoredChats, MonitoredChatError, parse_chat_link


def channel(chat_id=123):
    return types.Channel(chat_id, "Тестовый канал", types.ChatPhotoEmpty(), None,
                         broadcast=True, left=False)


class MonitoredChatsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "settings.json"
        self.settings = MonitorSettings(self.path)
        self.client = AsyncMock()
        self.client.get_entity.return_value = channel()
        self.client.get_permissions.return_value = SimpleNamespace(has_left=False)
        self.client.get_messages.return_value = []
        self.service = MonitoredChats(self.client, self.settings)

    async def assert_error(self, code, awaitable):
        with self.assertRaises(MonitoredChatError) as raised:
            await awaitable
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(self.settings.get_chats(), [])
        return raised.exception

    async def test_public_link_checks_membership_and_read_access(self):
        record = await self.service.add_link("t.me/TestChannel")
        self.assertEqual(record, {"id": -1000000000123, "title": "Тестовый канал",
                                  "link": "t.me/TestChannel"})
        self.client.get_entity.assert_awaited_once_with("testchannel")
        self.client.get_permissions.assert_awaited_once_with(self.client.get_entity.return_value, "me")
        self.client.get_messages.assert_awaited_once_with(self.client.get_entity.return_value, limit=1)
        self.client.assert_not_awaited()
        self.assertEqual(MonitorSettings(self.path).get_chat(record["id"]), record)

    async def test_basic_group_uses_negative_event_id(self):
        self.client.get_entity.return_value = types.Chat(
            77, "Group", types.ChatPhotoEmpty(), 1, None, 1)
        record = await self.service.add_link("https://t.me/groupname")
        self.assertEqual(record["id"], -77)

    async def test_invite_formats_preserve_case_without_joining(self):
        for link in ("https://t.me/+AbC_d-E", "t.me/joinchat/AbC_d-E"):
            self.client.return_value = types.ChatInviteAlready(channel())
            record = await self.service.add_link(link)
            request = self.client.await_args.args[0]
            self.assertIsInstance(request, CheckChatInviteRequest)
            self.assertEqual(request.hash, "AbC_d-E")
            self.assertEqual(record["id"], -1000000000123)
        self.client.get_entity.assert_not_awaited()
        self.assertTrue(all(isinstance(call.args[0], CheckChatInviteRequest)
                            for call in self.client.await_args_list))

    async def test_preview_invite_without_membership_is_rejected(self):
        self.client.return_value = types.ChatInvitePeek(channel(), None)
        await self.assert_error("access_denied", self.service.add_link("t.me/+AbCd"))
        self.client.get_messages.assert_not_awaited()

    async def test_deduplicate_aliases_and_invites_by_numeric_id(self):
        original = await self.service.add_link("t.me/firstalias")
        self.assertEqual(await self.service.add_link("t.me/secondalias"), original)
        self.client.return_value = types.ChatInviteAlready(channel())
        self.assertEqual(await self.service.add_link("t.me/+CaseSensitive"), original)
        self.assertEqual(len(self.service.get_chats()), 1)

    async def test_entity_entry_point_needs_no_link(self):
        entity = channel()
        record = await self.service.add_entity(entity)
        self.client.get_entity.assert_awaited_once_with(entity)
        self.assertEqual(record["link"], "")
        self.assertEqual(record["id"], -1000000000123)

    async def test_invalid_links_do_not_call_telegram(self):
        for link in (None, "", "@username", "https://evil.test/name",
                     "https://t.me/name/123", "https://t.me/c/123/4",
                     "https://t.me/share", "https://t.me/name?x=y", "http://[bad"):
            await self.assert_error("invalid_link", self.service.add_link(link))
        self.client.get_entity.assert_not_awaited()
        self.client.assert_not_awaited()

    async def test_user_and_forbidden_entities_are_rejected(self):
        for entity in (types.User(1), types.ChannelForbidden(2, 3, "Forbidden")):
            self.client.get_entity.return_value = entity
            await self.assert_error("invalid_chat_type", self.service.add_link("t.me/testname"))

    async def test_left_or_unreadable_chat_is_not_saved(self):
        entity = channel()
        entity.left = True
        self.client.get_entity.return_value = entity
        await self.assert_error("access_denied", self.service.add_link("t.me/testname"))
        entity.left = False
        self.client.get_permissions.return_value = None
        await self.assert_error("access_denied", self.service.add_link("t.me/testname"))
        self.client.get_permissions.return_value = SimpleNamespace(has_left=True)
        await self.assert_error("access_denied", self.service.add_link("t.me/testname"))
        self.client.get_permissions.return_value = SimpleNamespace(
            has_left=False, participant=SimpleNamespace(
                banned_rights=SimpleNamespace(view_messages=True)))
        await self.assert_error("access_denied", self.service.add_link("t.me/testname"))

    async def test_read_history_failure_does_not_save(self):
        self.client.get_messages.side_effect = errors.ChannelPrivateError(None)
        await self.assert_error("access_denied", self.service.add_link("t.me/testname"))

    async def test_telegram_errors_are_translated(self):
        for exc, code in (
            (errors.UsernameNotOccupiedError(None), "not_found"),
            (errors.UserNotParticipantError(None), "access_denied"),
            (errors.AuthKeyUnregisteredError(None), "unauthorized"),
            (errors.FloodWaitError(None, 42), "rate_limited"),
            (ConnectionError("offline"), "unavailable"),
            (TimeoutError(), "unavailable"),
            (errors.RPCError(None, "UNKNOWN", 500), "telegram_error"),
        ):
            self.client.get_entity.side_effect = exc
            result = await self.assert_error(code, self.service.add_link("t.me/testname"))
            if code == "rate_limited":
                self.assertEqual(result.retry_after, 42)

    async def test_expired_or_invalid_invite(self):
        for exc in (errors.InviteHashExpiredError(None), errors.InviteHashInvalidError(None)):
            self.client.side_effect = exc
            await self.assert_error("invalid_invite", self.service.add_link("t.me/+AbCd"))

    async def test_delete_saved_links_and_ids_without_network(self):
        for link, reference in (("https://t.me/TestName", "t.me/testname"),
                                ("https://t.me/+AbCd", "t.me/joinchat/AbCd"),
                                ("", -1000000000123)):
            self.settings.save_chat(-1000000000123, "Saved", link)
            self.service.delete_chat(reference)
            self.assertEqual(self.service.get_chats(), [])
        self.assertEqual(self.client.mock_calls, [])

    async def test_unknown_delete_reports_not_found_and_preserves_others(self):
        self.settings.save_chat(-1000000000123, "Saved", "t.me/testname")
        for reference in (-77, "t.me/unknown"):
            with self.assertRaises(MonitoredChatError) as raised:
                self.service.delete_chat(reference)
            self.assertEqual(raised.exception.code, "not_found")
        self.assertEqual(len(self.service.get_chats()), 1)

    async def test_corrupt_storage_is_not_overwritten(self):
        self.path.write_bytes(b"broken")
        with self.assertRaises(MonitoredChatError) as raised:
            await self.service.add_link("t.me/testname")
        self.assertEqual(raised.exception.code, "storage_error")
        for action in (self.service.get_chats, lambda: self.service.delete_chat(-123)):
            with self.assertRaises(MonitoredChatError) as raised:
                action()
            self.assertEqual(raised.exception.code, "storage_error")
        self.assertEqual(self.path.read_bytes(), b"broken")

    async def test_registration_preserves_mode(self):
        self.settings.set_mode("advanced")
        await self.service.add_link("t.me/testname")
        self.assertEqual(self.settings.get_mode(), "advanced")

    async def test_disk_error_is_distinct_from_network_error(self):
        with patch.object(self.settings, "save_chat", side_effect=OSError("disk full")):
            await self.assert_error("storage_error", self.service.add_link("t.me/testname"))

    def set_dialogs(self, *entities):
        self.client.get_dialogs.return_value = [
            SimpleNamespace(id=utils.get_peer_id(entity), entity=entity) for entity in entities
        ]

    async def test_group_id_with_or_without_minus(self):
        entity = types.Chat(123456789, 'Group', types.ChatPhotoEmpty(), 1, None, 1)
        self.set_dialogs(entity)
        for value in ('123456789', '-123456789', 123456789):
            record = await self.service.add_input(value)
            self.assertEqual(record['id'], utils.get_peer_id(entity))
        self.assertEqual(len(self.settings.get_chats()), 1)
        self.client.get_entity.assert_not_awaited()

    async def test_supergroup_and_channel_ids_are_canonical(self):
        for megagroup in (True, False):
            entity = channel(987654321)
            entity.megagroup = megagroup
            entity.broadcast = not megagroup
            self.set_dialogs(entity)
            for value in (str(entity.id), str(-entity.id), str(utils.get_peer_id(entity))):
                record = await self.service.add_input(value)
                self.assertEqual(record['id'], utils.get_peer_id(entity))
                self.assertEqual(record['link'], '')
            self.assertEqual(len(self.settings.get_chats()), 1)

    async def test_full_id_exact_match_takes_priority(self):
        group = types.Chat(123, 'Group', types.ChatPhotoEmpty(), 1, None, 1)
        broadcast = channel(123)
        self.set_dialogs(group, broadcast)
        self.assertEqual((await self.service.add_input('-123'))['id'], -123)
        self.assertEqual((await self.service.add_input(str(utils.get_peer_id(broadcast))))['id'],
                         utils.get_peer_id(broadcast))

    async def test_raw_id_collision_requires_selection_without_saving(self):
        group = types.Chat(123, 'Group', types.ChatPhotoEmpty(), 1, None, 1)
        broadcast = channel(123)
        self.set_dialogs(group, broadcast, broadcast)
        error = await self.assert_error('ambiguous_id', self.service.add_input('123'))
        self.assertEqual({chat['id'] for chat in error.candidates},
                         {utils.get_peer_id(group), utils.get_peer_id(broadcast)})
        self.client.get_messages.assert_not_awaited()

    async def test_unknown_ids_and_user_dialogs_are_not_saved(self):
        self.set_dialogs(types.User(123))
        for value in ('123', '-123', '-1000000000123', '0', '999'):
            await self.assert_error('id_not_found', self.service.add_input(value))
        self.client.get_permissions.assert_not_awaited()

    async def test_stale_or_unreadable_dialog_is_not_saved(self):
        entity = channel()
        entity.left = True
        self.set_dialogs(entity)
        await self.assert_error('id_not_found', self.service.add_input('123'))
        entity.left = False
        self.client.get_messages.side_effect = errors.ChannelPrivateError(None)
        await self.assert_error('access_denied', self.service.add_input('123'))

    async def test_ids_and_links_share_duplicate_detection(self):
        original = await self.service.add_input('t.me/testname')
        self.set_dialogs(channel())
        self.assertEqual(await self.service.add_input('123'), original)
        self.assertEqual(len(self.settings.get_chats()), 1)

    async def test_selected_exact_id_never_falls_back_to_another_chat(self):
        self.set_dialogs(channel(123))
        await self.assert_error('id_not_found', self.service.add_id(-123, exact_only=True))

    async def test_dialog_errors_are_translated(self):
        self.client.get_dialogs.side_effect = errors.FloodWaitError(None, 15)
        error = await self.assert_error('rate_limited', self.service.add_input('123'))
        self.assertEqual(error.retry_after, 15)

    async def test_invalid_id_is_reported_without_telegram_requests(self):
        for value in (True, None, 'hello', 1.5):
            await self.assert_error('invalid_id', self.service.add_id(value))
        self.client.get_dialogs.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
