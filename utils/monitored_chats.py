"""Chat registration using an injected, already running Telethon client.

No login, join, disconnect or monitoring side effects are performed here.
"""

import re
from urllib.parse import urlsplit

from telethon import errors, types, utils
from telethon.tl.functions.messages import CheckChatInviteRequest

from utils.monitor_settings import MonitorSettingsError


class MonitoredChatError(Exception):
    """A service error with a stable code and optional retry delay."""

    def __init__(self, code, message, retry_after=None, candidates=None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after
        self.candidates = candidates or []


def parse_chat_link(link):
    """Return (public|invite, identifier), preserving invitation hash case."""
    if not isinstance(link, str):
        raise MonitoredChatError("invalid_link", "Expected a Telegram chat link")
    value = link.strip()
    if value.lower().startswith("t.me/"):
        value = "https://" + value
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise MonitoredChatError("invalid_link", "Malformed Telegram link") from exc
    if (parsed.scheme not in ("http", "https") or parsed.netloc.lower() != "t.me"
            or parsed.query or parsed.fragment):
        raise MonitoredChatError("invalid_link", "Expected a t.me chat or invitation link")
    path = parsed.path.strip("/")
    invite = re.fullmatch(r"(?:\+|joinchat/)([A-Za-z0-9_-]+)", path)
    if invite:
        return "invite", invite.group(1)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", path) and path.lower() not in {
        "joinchat", "share", "proxy", "socks", "addstickers", "addemoji", "login",
    }:
        return "public", path.lower()
    raise MonitoredChatError("invalid_link", "Unsupported Telegram chat link")


class MonitoredChats:
    def __init__(self, client, settings):
        # Pass config.bot_config.client and the shared MonitorSettings instance.
        # Injecting them avoids initializing Telegram or configuration at import.
        self.client = client
        self.settings = settings

    @staticmethod
    def _translate(exc):
        if isinstance(exc, errors.FloodWaitError):
            return MonitoredChatError("rate_limited", "Telegram request limit reached", exc.seconds)
        if isinstance(exc, (errors.InviteHashInvalidError, errors.InviteHashExpiredError)):
            return MonitoredChatError("invalid_invite", "Invitation is invalid or expired")
        if isinstance(exc, (errors.UsernameInvalidError, errors.UsernameNotOccupiedError)):
            return MonitoredChatError("not_found", "Chat was not found")
        if isinstance(exc, (errors.ChannelPrivateError, errors.UserNotParticipantError,
                            errors.ChatAdminRequiredError)):
            return MonitoredChatError("access_denied", "Account has no confirmed access to this chat")
        if isinstance(exc, errors.UnauthorizedError):
            return MonitoredChatError("unauthorized", "Telegram session is not authorized")
        if isinstance(exc, MonitorSettingsError):
            return MonitoredChatError("storage_error", "Could not read or save monitoring settings")
        if isinstance(exc, (OSError, TimeoutError)):
            return MonitoredChatError("unavailable", "Telegram connection is unavailable")
        if isinstance(exc, ValueError):
            return MonitoredChatError("not_found", "Chat could not be resolved")
        return MonitoredChatError("telegram_error", "Telegram could not complete the request")

    async def add_link(self, link):
        kind, identifier = parse_chat_link(link)
        try:
            if kind == "invite":
                invite = await self.client(CheckChatInviteRequest(identifier))
                if not isinstance(invite, types.ChatInviteAlready):
                    raise MonitoredChatError("access_denied", "Join the chat manually before adding it")
                entity = invite.chat
            else:
                entity = await self.client.get_entity(identifier)
            return await self._verify_and_save(entity, link.strip())
        except MonitoredChatError:
            raise
        except (errors.RPCError, ValueError, OSError, TimeoutError) as exc:
            raise self._translate(exc) from exc

    async def add_input(self, reference):
        """Accept either a Telegram link or a user-facing numeric ID."""
        if type(reference) is int or (
            isinstance(reference, str) and re.fullmatch(r'-?[0-9]+', reference.strip())
        ):
            return await self.add_id(reference)
        return await self.add_link(reference)

    async def add_id(self, reference, *, exact_only=False):
        """Resolve dialog IDs first, then raw entity IDs, without guessing prefixes."""
        if type(reference) is not int and not (
            isinstance(reference, str) and re.fullmatch(r'-?[0-9]+', reference.strip())
        ):
            raise MonitoredChatError('invalid_id', 'Expected a numeric Telegram chat ID')
        try:
            requested_id = int(reference)
        except ValueError as exc:
            raise MonitoredChatError('invalid_id', 'Invalid numeric chat ID') from exc
        try:
            exact, raw = {}, {}
            for dialog in await self.client.get_dialogs(limit=None):
                entity = dialog.entity
                if not isinstance(entity, (types.Chat, types.Channel)):
                    continue
                if (entity.left or getattr(entity, 'deactivated', False)
                        or getattr(entity, 'migrated_to', None)):
                    continue
                canonical_id = utils.get_peer_id(entity)
                if canonical_id == requested_id:
                    exact[canonical_id] = entity
                if entity.id == abs(requested_id):
                    raw[canonical_id] = entity
            matches = exact if exact_only else (exact or raw)
            if not matches:
                raise MonitoredChatError('id_not_found', 'No accessible group or channel matches this ID')
            if len(matches) > 1:
                raise MonitoredChatError(
                    'ambiguous_id', 'Several chats match; select one explicitly',
                    candidates=[{'id': chat_id, 'title': entity.title}
                                for chat_id, entity in matches.items()],
                )
            return await self._verify_and_save(next(iter(matches.values())), '')
        except MonitoredChatError:
            raise
        except (errors.RPCError, ValueError, OSError, TimeoutError) as exc:
            raise self._translate(exc) from exc

    async def add_entity(self, entity):
        """Future dialog selection entry point; still rechecks current access."""
        try:
            resolved = await self.client.get_entity(entity)
            return await self._verify_and_save(resolved, "")
        except MonitoredChatError:
            raise
        except (errors.RPCError, ValueError, OSError, TimeoutError) as exc:
            raise self._translate(exc) from exc

    async def _verify_and_save(self, entity, link):
        if not isinstance(entity, (types.Chat, types.Channel)):
            raise MonitoredChatError("invalid_chat_type", "Only groups and channels are supported")
        if (entity.left or getattr(entity, "deactivated", False)
                or getattr(entity, "migrated_to", None)):
            raise MonitoredChatError("access_denied", "Chat is unavailable or has migrated")
        permissions = await self.client.get_permissions(entity, "me")
        if permissions is None:
            raise MonitoredChatError("access_denied", "Account membership could not be confirmed")
        participant = getattr(permissions, "participant", None)
        rights = getattr(participant, "banned_rights", None)
        if (getattr(permissions, "has_left", False)
                or getattr(participant, "left", False)
                or getattr(rights, "view_messages", False)):
            raise MonitoredChatError("access_denied", "Account cannot read this chat")
        # Successful empty history is valid too; no message is required to exist.
        await self.client.get_messages(entity, limit=1)
        chat_id = utils.get_peer_id(entity)
        existing = self._storage_call(self.settings.get_chat, chat_id)
        if existing is not None:
            return existing
        self._storage_call(self.settings.save_chat, chat_id, entity.title, link)
        return self._storage_call(self.settings.get_chat, chat_id)

    @staticmethod
    def _storage_call(operation, *args):
        try:
            return operation(*args)
        except (MonitorSettingsError, OSError) as exc:
            raise MonitoredChatError("storage_error", "Could not read or save monitoring settings") from exc

    def get_chats(self):
        return self._storage_call(self.settings.get_chats)

    def get_mode(self):
        return self._storage_call(self.settings.get_mode)

    def set_mode(self, mode):
        if mode not in ("simple", "advanced"):
            raise MonitoredChatError("invalid_mode", "Unknown monitoring mode")
        self._storage_call(self.settings.set_mode, mode)

    def is_chat_allowed(self, chat_id):
        """Check monitoring scope using only the marked numeric event.chat_id."""
        if type(chat_id) is not int:
            return False
        mode = self._storage_call(self.settings.get_mode)
        if mode == "advanced":
            return True
        return self._storage_call(self.settings.get_chat, chat_id) is not None

    def delete_chat(self, reference):
        """Remove by marked integer ID or previously saved link, entirely offline.

        If a username has changed or an invitation has expired, its saved link
        still works. Unknown aliases require the stored ID; no resolution occurs.
        """
        if type(reference) is int:
            chat_id = reference
        else:
            key = parse_chat_link(reference)
            chat_id = None
            for chat in self.get_chats():
                if chat["link"] and parse_chat_link(chat["link"]) == key:
                    chat_id = chat["id"]
                    break
            if chat_id is None:
                raise MonitoredChatError("not_found", "Chat is not in the saved list")
        if not self._storage_call(self.settings.delete_chat, chat_id):
            raise MonitoredChatError("not_found", "Chat is not in the saved list")
