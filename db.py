import os
import sqlite3
from datetime import datetime
from typing import List, Optional, Tuple
import pytz

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reminders.db")
KYIV = pytz.timezone("Europe/Kyiv")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_sent INTEGER DEFAULT 0
            )
            """
        )
        conn.commit()


def add_reminder(chat_id: int, text: str, remind_at: datetime) -> int:
    init_db()
    now_str = datetime.now(KYIV).isoformat()
    remind_str = remind_at.astimezone(KYIV).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO reminders (chat_id, text, remind_at, created_at, is_sent)
            VALUES (?, ?, ?, ?, 0)
            """,
            (chat_id, text, remind_str, now_str),
        )
        conn.commit()
        return cursor.lastrowid


def get_due_reminders(now_dt: Optional[datetime] = None) -> List[sqlite3.Row]:
    init_db()
    if now_dt is None:
        now_dt = datetime.now(KYIV)
    now_str = now_dt.astimezone(KYIV).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM reminders
            WHERE is_sent = 0 AND remind_at <= ?
            ORDER BY remind_at ASC
            """,
            (now_str,),
        )
        return cursor.fetchall()


def mark_as_sent(reminder_id: int):
    with get_connection() as conn:
        conn.execute(
            "UPDATE reminders SET is_sent = 1 WHERE id = ?",
            (reminder_id,),
        )
        conn.commit()


def get_active_reminders(chat_id: int) -> List[sqlite3.Row]:
    init_db()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM reminders
            WHERE chat_id = ? AND is_sent = 0
            ORDER BY remind_at ASC
            """,
            (chat_id,),
        )
        return cursor.fetchall()


def delete_reminder(reminder_id: int, chat_id: int) -> bool:
    init_db()
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM reminders WHERE id = ? AND chat_id = ?",
            (reminder_id, chat_id),
        )
        conn.commit()
        return cursor.rowcount > 0
