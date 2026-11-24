"""SQLite database manager and session/message repository.

Handles auto-schema creation, parent directory creation, WAL mode,
and atomic transactions for conversation turns.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings


def get_utc_now_iso() -> str:
    """Return current server time in ISO-8601 UTC format."""
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_db():
    """Context manager providing a thread-safe SQLite connection with WAL mode."""
    db_path = settings.sqlite_path

    # If file-based SQLite, ensure the parent directory exists
    if db_path != ":memory:":
        parent_dir = os.path.dirname(os.path.abspath(db_path))
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        # Enable WAL mode for concurrent reads/writes and enforce foreign keys
        if db_path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
    finally:
        conn.close()


def init_db():
    """Initialize database tables and indexes on application startup."""
    with get_db() as conn:
        with conn:
            # Sessions table: stores session_id and per-session system prompt
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    system_prompt TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

            # Messages table: stores multi-turn user and assistant messages
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

            # Index on session_id for high-performance history retrieval
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_session_id
                ON messages (session_id);
                """
            )


def check_db_reachable() -> bool:
    """Check if the database is accessible and functional."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1;")
            return cursor.fetchone() is not None
    except Exception:
        return False


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve session record by session_id."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT session_id, system_prompt, created_at FROM sessions WHERE session_id = ?;",
            (session_id,),
        )
        row = cursor.fetchone()
        if row:
            return {
                "session_id": row["session_id"],
                "system_prompt": row["system_prompt"],
                "created_at": row["created_at"],
            }
        return None


def upsert_session(session_id: str, system_prompt: Optional[str]) -> str:
    """Ensure session exists and update system_prompt if provided.

    Returns the effective system prompt for this session.
    """
    now = get_utc_now_iso()
    with get_db() as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT session_id, system_prompt FROM sessions WHERE session_id = ?;",
                (session_id,),
            )
            row = cursor.fetchone()

            if row is None:
                # New session
                effective_prompt = (
                    system_prompt
                    if system_prompt is not None and system_prompt.strip()
                    else settings.DEFAULT_SYSTEM_PROMPT
                )
                cursor.execute(
                    """
                    INSERT INTO sessions (session_id, system_prompt, created_at)
                    VALUES (?, ?, ?);
                    """,
                    (session_id, effective_prompt, now),
                )
                return effective_prompt
            else:
                # Existing session
                if system_prompt is not None and system_prompt.strip():
                    effective_prompt = system_prompt.strip()
                    cursor.execute(
                        """
                        UPDATE sessions
                        SET system_prompt = ?
                        WHERE session_id = ?;
                        """,
                        (effective_prompt, session_id),
                    )
                else:
                    effective_prompt = row["system_prompt"] or settings.DEFAULT_SYSTEM_PROMPT
                return effective_prompt


def get_session_history_for_llm(session_id: str) -> List[Dict[str, str]]:
    """Get history formatted for LiteLLM completion calls (role and content only, oldest first)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT role, content
            FROM messages
            WHERE session_id = ?
            ORDER BY id ASC;
            """,
            (session_id,),
        )
        rows = cursor.fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]


def get_session_messages_endpoint(session_id: str) -> Optional[List[Dict[str, Any]]]:
    """Get messages for GET /sessions/{session_id}/messages endpoint.

    Returns:
        List of message dicts oldest first, NO system prompt.
        metadata only on assistant messages (resolution_source, input_tokens, output_tokens).
        Returns None if session does not exist.
    """
    with get_db() as conn:
        # Check if session exists
        cursor = conn.cursor()
        cursor.execute(
            "SELECT session_id FROM sessions WHERE session_id = ?;",
            (session_id,),
        )
        if not cursor.fetchone():
            return None

        cursor.execute(
            """
            SELECT role, content, metadata
            FROM messages
            WHERE session_id = ?
            ORDER BY id ASC;
            """,
            (session_id,),
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            msg_dict: Dict[str, Any] = {
                "role": row["role"],
                "content": row["content"],
            }
            if row["role"] == "assistant" and row["metadata"]:
                try:
                    full_meta = json.loads(row["metadata"])
                    # Contract requirement: metadata only on assistant messages and must include
                    # resolution_source, input_tokens, output_tokens.
                    msg_dict["metadata"] = {
                        "resolution_source": full_meta.get("resolution_source"),
                        "input_tokens": full_meta.get("input_tokens"),
                        "output_tokens": full_meta.get("output_tokens"),
                    }
                except Exception:
                    pass
            result.append(msg_dict)
        return result


def insert_chat_turn(
    session_id: str,
    user_content: str,
    assistant_content: str,
    metadata_dict: Dict[str, Any],
):
    """Insert user message and assistant message atomically in one transaction."""
    now = get_utc_now_iso()
    meta_json = json.dumps(metadata_dict)

    with get_db() as conn:
        with conn:
            cursor = conn.cursor()
            # 1. Insert user message
            cursor.execute(
                """
                INSERT INTO messages (session_id, role, content, metadata, created_at)
                VALUES (?, 'user', ?, NULL, ?);
                """,
                (session_id, user_content, now),
            )
            # 2. Insert assistant message
            cursor.execute(
                """
                INSERT INTO messages (session_id, role, content, metadata, created_at)
                VALUES (?, 'assistant', ?, ?, ?);
                """,
                (session_id, assistant_content, meta_json, now),
            )
