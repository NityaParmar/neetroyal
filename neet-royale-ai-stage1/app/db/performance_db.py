"""
SQLite database for match performance tracking.

Two tables here — completely separate from the question bank (registry.db):
  - match_sessions : one row per match round a user plays
  - match_answers  : one row per question the user answered in that round

This is the DB the performance-summary endpoint reads from to build the
per-user report (question + chosen answer + correct/incorrect + source link).

DB lives at  data/performance.db  so it's easy to wipe independently of
the question bank during dev/testing.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "performance.db"

SCHEMA_SESSIONS = """
CREATE TABLE IF NOT EXISTS match_sessions (
    id           TEXT PRIMARY KEY,          -- UUID supplied by the gateway/backend
    user_id      TEXT NOT NULL,
    match_id     TEXT NOT NULL,
    subject      TEXT,                      -- NULL = mixed, else 'physics'/'chemistry'/'biology'
    started_at   TEXT NOT NULL,
    ended_at     TEXT,                      -- NULL while the match is still live
    status       TEXT NOT NULL DEFAULT 'active'  -- 'active' | 'completed'
);
"""

SCHEMA_ANSWERS = """
CREATE TABLE IF NOT EXISTS match_answers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL,
    question_id         INTEGER NOT NULL,   -- FK into questions table in registry.db
    question_text       TEXT NOT NULL,      -- denormalised so performance summary works without joining across DBs
    option_a            TEXT NOT NULL,
    option_b            TEXT NOT NULL,
    option_c            TEXT NOT NULL,
    option_d            TEXT NOT NULL,
    correct_answer      TEXT NOT NULL,
    chosen_answer       TEXT NOT NULL,      -- what the user picked: A/B/C/D
    is_correct          INTEGER NOT NULL,   -- 1 if correct, 0 if not  (SQLite booleans are integers)
    subject             TEXT NOT NULL,
    topic               TEXT NOT NULL,
    source_url          TEXT NOT NULL,      -- resolved at answer-record time from source_registry
    source_page         INTEGER,
    answered_at         TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES match_sessions(id)
);
"""


@contextmanager
def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(SCHEMA_SESSIONS)
        conn.execute(SCHEMA_ANSWERS)


# ---------------------------------------------------------------------------
# match_sessions helpers
# ---------------------------------------------------------------------------

def create_session(session_id: str, user_id: str, match_id: str, subject: str | None) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO match_sessions (id, user_id, match_id, subject, started_at, status)
            VALUES (?, ?, ?, ?, ?, 'active')
            ON CONFLICT(id) DO NOTHING
            """,
            (session_id, user_id, match_id, subject, datetime.now(timezone.utc).isoformat()),
        )


def end_session(session_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE match_sessions SET ended_at = ?, status = 'completed' WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), session_id),
        )


def get_session(session_id: str) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM match_sessions WHERE id = ?", (session_id,)
        ).fetchone()


# ---------------------------------------------------------------------------
# match_answers helpers
# ---------------------------------------------------------------------------

@dataclass
class AnswerRecord:
    session_id: str
    question_id: int
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str
    chosen_answer: str
    is_correct: int          # 1 or 0
    subject: str
    topic: str
    source_url: str
    source_page: int | None
    answered_at: str


def record_answer(record: AnswerRecord) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO match_answers
                (session_id, question_id, question_text, option_a, option_b, option_c, option_d,
                 correct_answer, chosen_answer, is_correct, subject, topic,
                 source_url, source_page, answered_at)
            VALUES
                (:session_id, :question_id, :question_text, :option_a, :option_b, :option_c, :option_d,
                 :correct_answer, :chosen_answer, :is_correct, :subject, :topic,
                 :source_url, :source_page, :answered_at)
            """,
            asdict(record),
        )
        return cursor.lastrowid


def get_answers_for_session(session_id: str) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM match_answers WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()


def has_answer_for_question(session_id: str, question_id: int) -> bool:
    """Prevents duplicate answer records if the user somehow submits twice."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM match_answers WHERE session_id = ? AND question_id = ?",
            (session_id, question_id),
        ).fetchone()
        return row["c"] > 0
