"""
SQLite registry for source documents.

Every downloaded PDF gets one row here. This table is the join point
between "where a question came from" and "what file/URL to show the user."
Later, the questions table (Stage 3) will store a `source_document_id`
foreign key pointing back to this table instead of duplicating the URL
on every single question row.

Swap-out note: this uses sqlite3 for zero-setup local dev. When you wire
this into your teammates' shared DB (Postgres/Mongo), keep the same
column names/shape below (`SourceDocumentRecord`) so nothing upstream
(downloader.py) has to change — just swap out the storage functions.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "registry.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    source_url      TEXT NOT NULL,
    subject         TEXT NOT NULL,
    doc_type        TEXT NOT NULL,
    year            INTEGER,
    local_path      TEXT NOT NULL,
    sha256          TEXT NOT NULL,
    downloaded_at   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'downloaded'
);
"""


@dataclass
class SourceDocumentRecord:
    name: str
    source_url: str
    subject: str
    doc_type: str
    year: int | None
    local_path: str
    sha256: str
    downloaded_at: str
    status: str = "downloaded"


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


def upsert_source_document(record: SourceDocumentRecord) -> int:
    """Insert a source document, or update it if the name already exists
    (re-running ingestion should not create duplicate rows)."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO source_documents
                (name, source_url, subject, doc_type, year, local_path, sha256, downloaded_at, status)
            VALUES
                (:name, :source_url, :subject, :doc_type, :year, :local_path, :sha256, :downloaded_at, :status)
            ON CONFLICT(name) DO UPDATE SET
                source_url=excluded.source_url,
                local_path=excluded.local_path,
                sha256=excluded.sha256,
                downloaded_at=excluded.downloaded_at,
                status=excluded.status
            """,
            asdict(record),
        )
        row = conn.execute(
            "SELECT id FROM source_documents WHERE name = ?", (record.name,)
        ).fetchone()
        return row["id"]


def mark_failed(name: str, source_url: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO source_documents
                (name, source_url, subject, doc_type, year, local_path, sha256, downloaded_at, status)
            VALUES (?, ?, 'unknown', 'unknown', NULL, '', '', ?, 'failed')
            ON CONFLICT(name) DO UPDATE SET status='failed', downloaded_at=excluded.downloaded_at
            """,
            (name, source_url, datetime.now(timezone.utc).isoformat()),
        )


def list_source_documents(status: str | None = None) -> list[sqlite3.Row]:
    with get_connection() as conn:
        if status:
            return conn.execute(
                "SELECT * FROM source_documents WHERE status = ?", (status,)
            ).fetchall()
        return conn.execute("SELECT * FROM source_documents").fetchall()


def get_source_url(document_id: int) -> str | None:
    """Used later by the performance-summary endpoint to resolve a
    question's source_document_id back into the URL shown to the user."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT source_url FROM source_documents WHERE id = ?", (document_id,)
        ).fetchone()
        return row["source_url"] if row else None
