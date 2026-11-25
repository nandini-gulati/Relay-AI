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
            # Users table: stores registered accounts
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    is_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )

            # Sessions table: stores session_id, optional owner user_id, and per-session system prompt
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    system_prompt TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

            # Migrate existing sessions table if user_id column is missing
            cols = [
                row["name"]
                for row in conn.execute("PRAGMA table_info(sessions);").fetchall()
            ]
            if "user_id" not in cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN user_id INTEGER;")

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


def upsert_session(
    session_id: str,
    system_prompt: Optional[str],
    user_id: Optional[int] = None,
) -> str:
    """Ensure session exists and update system_prompt if provided.

    Returns the effective system prompt for this session.
    """
    now = get_utc_now_iso()
    with get_db() as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT session_id, user_id, system_prompt FROM sessions WHERE session_id = ?;",
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
                    INSERT INTO sessions (session_id, user_id, system_prompt, created_at)
                    VALUES (?, ?, ?, ?);
                    """,
                    (session_id, user_id, effective_prompt, now),
                )
                return effective_prompt
            else:
                # Existing session: prevent cross-user hijacking
                if row["user_id"] is not None and row["user_id"] != user_id:
                    raise PermissionError("Session belongs to another user")
                if row["user_id"] is None and user_id is not None:
                    cursor.execute(
                        "UPDATE sessions SET user_id = ? WHERE session_id = ?;",
                        (user_id, session_id),
                    )
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


def get_session_messages_endpoint(
    session_id: str,
    user_id: Optional[int] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Get messages for GET /sessions/{session_id}/messages endpoint.

    Returns:
        List of message dicts oldest first, NO system prompt.
        metadata only on assistant messages (resolution_source, input_tokens, output_tokens).
        Returns None if session does not exist or is owned by a different user.
    """
    with get_db() as conn:
        # Check if session exists and verify ownership
        cursor = conn.cursor()
        cursor.execute(
            "SELECT session_id, user_id FROM sessions WHERE session_id = ?;",
            (session_id,),
        )
        session_row = cursor.fetchone()
        if not session_row:
            return None
        owner_id = session_row["user_id"]
        if owner_id is not None and owner_id != user_id:
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


def list_sessions(user_id: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Return recent non-empty chat sessions for the given user, ordered by latest activity."""
    if user_id is None:
        return []

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                s.session_id,
                s.created_at,
                MAX(m.created_at) AS updated_at,
                COUNT(m.id) AS message_count,
                (
                    SELECT m2.content
                    FROM messages m2
                    WHERE m2.session_id = s.session_id AND m2.role = 'user'
                    ORDER BY m2.id ASC
                    LIMIT 1
                ) AS first_user_message
            FROM sessions s
            INNER JOIN messages m ON m.session_id = s.session_id
            WHERE s.user_id = ?
            GROUP BY s.session_id
            ORDER BY updated_at DESC
            LIMIT ?;
            """,
            (user_id, limit),
        )
        rows = cursor.fetchall()
        sessions = []
        for row in rows:
            raw_title = (row["first_user_message"] or "New chat").strip().replace("\n", " ")
            title = raw_title[:56] + ("…" if len(raw_title) > 56 else "")
            sessions.append({
                "session_id": row["session_id"],
                "title": title,
                "updated_at": row["updated_at"] or row["created_at"],
                "message_count": int(row["message_count"] or 0),
            })
        return sessions


def delete_session(session_id: str, user_id: Optional[int] = None) -> bool:
    """Delete a user's session and all of its messages. Returns True if deleted."""
    if user_id is None:
        return False

    with get_db() as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT user_id FROM sessions WHERE session_id = ?;",
                (session_id,),
            )
            row = cursor.fetchone()
            if not row or row["user_id"] != user_id:
                return False
            cursor.execute("DELETE FROM messages WHERE session_id = ?;", (session_id,))
            cursor.execute("DELETE FROM sessions WHERE session_id = ?;", (session_id,))
            return cursor.rowcount > 0


# ── User & OTP Repository ──

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Fetch user record by normalized email."""
    norm = email.strip().lower()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash, is_verified, created_at FROM users WHERE email = ?;",
            (norm,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "email": row["email"],
            "password_hash": row["password_hash"],
            "is_verified": bool(row["is_verified"]),
            "created_at": row["created_at"],
        }


def create_user(email: str, password_hash: str) -> Dict[str, Any]:
    """Create a new user account (marked verified immediately for password auth)."""
    norm = email.strip().lower()
    now = get_utc_now_iso()
    with get_db() as conn:
        with conn:
            existing = conn.execute(
                "SELECT id FROM users WHERE email = ?;", (norm,)
            ).fetchone()
            if existing:
                raise ValueError("An account with this email already exists")
            cursor = conn.execute(
                "INSERT INTO users (email, password_hash, is_verified, created_at) VALUES (?, ?, 1, ?);",
                (norm, password_hash, now),
            )
            return {"id": cursor.lastrowid, "email": norm, "is_verified": True}
