"""Persistent settings for a single monitor process, without Telegram imports."""

import json
import os
from pathlib import Path
import tempfile
from threading import RLock


DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[1] / "config" / "monitor_settings.json"


class MonitorSettingsError(ValueError):
    """Existing settings are unreadable or invalid; the file is left untouched."""


class MonitorSettings:
    def __init__(self, file_path=None):
        self.file_path = (
            DEFAULT_SETTINGS_PATH if file_path is None else Path(file_path).resolve()
        )
        self._lock = RLock()

    @staticmethod
    def _validate_id(chat_id):
        if type(chat_id) is not int:
            raise ValueError("Telegram chat ID must be an integer")

    @classmethod
    def _validate(cls, data):
        if not isinstance(data, dict) or set(data) != {"mode", "chats"}:
            raise ValueError("Expected mode and chats fields")
        if data["mode"] not in ("simple", "advanced"):
            raise ValueError("Unknown monitoring mode")
        if not isinstance(data["chats"], list):
            raise ValueError("Chats must be a list")
        seen = set()
        for chat in data["chats"]:
            if not isinstance(chat, dict) or set(chat) != {"id", "title", "link"}:
                raise ValueError("Invalid chat record")
            cls._validate_id(chat["id"])
            if not isinstance(chat["title"], str) or not isinstance(chat["link"], str):
                raise ValueError("Chat title and link must be strings")
            if chat["id"] in seen:
                raise ValueError("Duplicate chat ID")
            seen.add(chat["id"])

    def _load(self):
        try:
            with self.file_path.open(encoding="utf-8") as stream:
                data = json.load(stream)
        except FileNotFoundError:
            return {"mode": "simple", "chats": []}
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise MonitorSettingsError(f"Invalid settings: {self.file_path}") from exc
        try:
            self._validate(data)
        except ValueError as exc:
            raise MonitorSettingsError(f"Invalid settings: {self.file_path}") from exc
        return data

    def _save(self, data):
        self._validate(data)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.file_path.parent,
                prefix=f".{self.file_path.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.file_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def get_mode(self):
        with self._lock:
            return self._load()["mode"]

    def set_mode(self, mode):
        if mode not in ("simple", "advanced"):
            raise ValueError("Mode must be simple or advanced")
        with self._lock:
            data = self._load()
            data["mode"] = mode
            self._save(data)

    def get_chats(self):
        with self._lock:
            return self._load()["chats"]

    def get_chat(self, chat_id):
        self._validate_id(chat_id)
        with self._lock:
            return next((chat for chat in self._load()["chats"] if chat["id"] == chat_id), None)

    def save_chat(self, chat_id, title="", link=""):
        """Insert or replace a chat by ID; access checks belong to the caller."""
        self._validate_id(chat_id)
        with self._lock:
            data = self._load()
            record = {"id": chat_id, "title": title, "link": link}
            for index, chat in enumerate(data["chats"]):
                if chat["id"] == chat_id:
                    data["chats"][index] = record
                    break
            else:
                data["chats"].append(record)
            self._save(data)

    def delete_chat(self, chat_id):
        self._validate_id(chat_id)
        with self._lock:
            data = self._load()
            remaining = [chat for chat in data["chats"] if chat["id"] != chat_id]
            if len(remaining) == len(data["chats"]):
                return False
            data["chats"] = remaining
            self._save(data)
            return True
