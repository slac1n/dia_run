"""Private local conversation storage, deliberately outside the synced data root."""

import json
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from dia_run.coach.models import CoachAnswer


class ChatStore:
    def __init__(self, *, path: Path, data_root: Path) -> None:
        if path.resolve().is_relative_to(data_root.resolve()):
            raise ValueError("Coach history must be outside the synced data root")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(path, 0o600)
        self.path = path
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
                messages TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                draft TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '')""")

            connection.execute("""CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, key TEXT NOT NULL, category TEXT NOT NULL,
                text TEXT NOT NULL, quote TEXT NOT NULL, context_quote TEXT NOT NULL,
                source_chat TEXT NOT NULL, created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL, UNIQUE(owner,key))""")

    def get_attempt(self, *, chat_id: str, owner: str) -> tuple[str, str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT draft,error FROM chats WHERE id=? AND owner=?", (chat_id, owner)
            ).fetchone()
        if row is None:
            raise ValueError("Conversation not found")
        return row[0], row[1]

    def record_attempt(self, *, chat_id: str, owner: str, question: str, error: str, revision: int) -> int:
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE chats SET draft=?,error=?,revision=revision+1 WHERE id=? AND owner=? AND revision=?",
                (question, error, chat_id, owner, revision),
            )
            if result.rowcount != 1:
                raise ValueError("Conversation changed; reload before retrying")
        return revision + 1

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA secure_delete=ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, *, owner: str) -> str:
        chat_id = uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO chats(id,owner,title,messages) VALUES(?,?,?,?)",
                (chat_id, owner, "New conversation", "[]"),
            )
        return chat_id

    def list_chats(self, *, owner: str) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id,title FROM chats WHERE owner=? ORDER BY rowid DESC", (owner,))
            return [{"id": row[0], "title": row[1]} for row in rows]

    def load(self, *, chat_id: str, owner: str) -> tuple[list[dict[str, Any]], int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT messages,revision FROM chats WHERE id=? AND owner=?", (chat_id, owner)
            ).fetchone()
        if row is None:
            raise ValueError("Conversation not found")
        return json.loads(row[0]), row[1]

    def save(
        self,
        *,
        chat_id: str,
        owner: str,
        messages: list[dict[str, Any]],
        revision: int,
        answer: CoachAnswer | None = None,
    ) -> None:
        title = next((m["content"][:80] for m in messages if m["role"] == "user"), "Coach")
        if answer:
            answer.validate_sources(messages=messages)
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE chats SET messages=?,title=?,draft='',error='',revision=revision+1 "
                "WHERE id=? AND owner=? AND revision=?",
                (json.dumps(messages, allow_nan=False), title, chat_id, owner, revision),
            )
            if changed.rowcount != 1:
                raise ValueError("Conversation changed; reload before retrying")

            if answer:
                now = datetime.now(timezone.utc)
                connection.execute("DELETE FROM memories WHERE expires_at<=?", (now.isoformat(),))
                for item in answer.forget_memories:
                    connection.execute("DELETE FROM memories WHERE id=? AND owner=?", (item.memory_id, owner))
                for update in answer.memory_updates:
                    duplicate = connection.execute(
                        "SELECT id FROM memories WHERE owner=? AND text=? AND key!=?",
                        (owner, update.text, update.key),
                    ).fetchone()
                    if duplicate:
                        continue
                    connection.execute(
                        """INSERT INTO memories(id,owner,key,category,text,quote,context_quote,
                            source_chat,created_at,expires_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(owner,key) DO UPDATE SET category=excluded.category,
                        text=excluded.text, quote=excluded.quote,
                        context_quote=excluded.context_quote,
                        source_chat=excluded.source_chat, created_at=excluded.created_at,
                        expires_at=excluded.expires_at""",
                        (
                            "M" + uuid4().hex,
                            owner,
                            update.key,
                            update.category,
                            update.text,
                            update.quote,
                            update.context_quote,
                            chat_id,
                            now.isoformat(),
                            (now + timedelta(days=update.retention_days)).isoformat(),
                        ),
                    )
                connection.execute(
                    """DELETE FROM memories WHERE owner=? AND id NOT IN
                    (SELECT id FROM memories WHERE owner=? ORDER BY created_at DESC, id DESC LIMIT 100)""",
                    (owner, owner),
                )

    def list_memories(self, *, owner: str) -> list[dict[str, str]]:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM memories WHERE owner=? AND expires_at>? ORDER BY created_at DESC,id",
                (owner, datetime.now(timezone.utc).isoformat()),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_memories(
        self, *, owner: str, query: str, limit: int = 5, include_context: bool = False
    ) -> list[dict[str, str]]:
        tokens = {word for word in re.findall(r"[^\W_]+", query.casefold()) if len(word) > 2}
        ranked = []
        for item in self.list_memories(owner=owner):
            words = set(re.findall(r"[^\W_]+", (item["text"] + " " + item["key"].replace("_", " ")).casefold()))
            score = len(tokens & words)
            if score or (include_context and item["category"] in {"preference", "goal", "schedule"}):
                ranked.append((score, item["created_at"], item["id"], item))
        ranked.sort(key=lambda entry: entry[:3], reverse=True)
        return [item[3] for item in ranked[: min(limit, 8)]]

    def forget_memory(self, *, memory_id: str, owner: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM memories WHERE id=? AND owner=?", (memory_id, owner))

    def delete(self, *, chat_id: str, owner: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM memories WHERE source_chat=? AND owner=?", (chat_id, owner))
            connection.execute("DELETE FROM chats WHERE id=? AND owner=?", (chat_id, owner))
