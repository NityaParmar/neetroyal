"""
SQLite table for extracted MCQs.

Each row references source_document_id (Stage 1) and page_number, so the
question's origin can always be traced back through source_registry.py to
get the real source_url shown in the post-match performance summary.

low_confidence rows (confidence < LOW_CONFIDENCE_THRESHOLD) are worth
surfacing separately for manual review, since correct_answer here was
inferred by the LLM rather than checked against an official answer key.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "registry.db"

LOW_CONFIDENCE_THRESHOLD = 0.6

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_document_id  INTEGER NOT NULL,
    page_number         INTEGER NOT NULL,
    question_text       TEXT NOT NULL,
    option_a            TEXT NOT NULL,
    option_b            TEXT NOT NULL,
    option_c            TEXT NOT NULL,
    option_d            TEXT NOT NULL,
    correct_answer      TEXT NOT NULL,
    subject             TEXT NOT NULL,
    topic               TEXT NOT NULL,
    confidence          REAL NOT NULL,
    FOREIGN KEY (source_document_id) REFERENCES source_documents(id)
);
"""


@dataclass
class QuestionRecord:
    source_document_id: int
    page_number: int
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str
    subject: str
    topic: str
    confidence: float


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
        conn.execute(SCHEMA)


def insert_question(record: QuestionRecord) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO questions
                (source_document_id, page_number, question_text, option_a, option_b,
                 option_c, option_d, correct_answer, subject, topic, confidence)
            VALUES
                (:source_document_id, :page_number, :question_text, :option_a, :option_b,
                 :option_c, :option_d, :correct_answer, :subject, :topic, :confidence)
            """,
            asdict(record),
        )
        return cursor.lastrowid


def has_questions_for_page(source_document_id: int, page_number: int) -> bool:
    """Used for idempotency — skip re-extracting a page that's already done."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM questions WHERE source_document_id = ? AND page_number = ?",
            (source_document_id, page_number),
        ).fetchone()
        return row["c"] > 0


def count_questions(source_document_id: int | None = None) -> int:
    with get_connection() as conn:
        if source_document_id is not None:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM questions WHERE source_document_id = ?",
                (source_document_id,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as c FROM questions").fetchone()
        return row["c"]


def get_low_confidence_questions(threshold: float = LOW_CONFIDENCE_THRESHOLD) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM questions WHERE confidence < ? ORDER BY confidence ASC",
            (threshold,),
        ).fetchall()


def get_random_questions(count: int, subject: str | None = None) -> list[sqlite3.Row]:
    """Used later by the match-serving endpoint to pull questions for a round."""
    with get_connection() as conn:
        if subject:
            return conn.execute(
                "SELECT * FROM questions WHERE subject = ? ORDER BY RANDOM() LIMIT ?",
                (subject, count),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM questions ORDER BY RANDOM() LIMIT ?", (count,)
        ).fetchall()


def get_question_by_id(question_id: int) -> sqlite3.Row | None:
    """Fetch a single question by its primary key."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM questions WHERE id = ?", (question_id,)
        ).fetchone()
