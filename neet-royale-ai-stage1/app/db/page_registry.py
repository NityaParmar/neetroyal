"""
SQLite table for extracted PDF page text.

Each row is one page of one source document. `extraction_method` records
whether the text came straight from the PDF's embedded text layer
('native') or had to be OCR'd from a rasterized page image ('ocr') —
useful later for debugging bad extractions, since OCR text is noisier.

Stage 3 (LLM extraction) reads from this table instead of re-parsing PDFs,
so extraction only has to run once per document.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "registry.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS extracted_pages (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_document_id  INTEGER NOT NULL,
    page_number         INTEGER NOT NULL,
    text                TEXT NOT NULL,
    extraction_method   TEXT NOT NULL,
    char_count          INTEGER NOT NULL,
    UNIQUE(source_document_id, page_number),
    FOREIGN KEY (source_document_id) REFERENCES source_documents(id)
);
"""


@dataclass
class ExtractedPageRecord:
    source_document_id: int
    page_number: int
    text: str
    extraction_method: str  # 'native' or 'ocr'
    char_count: int


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


def upsert_page(record: ExtractedPageRecord) -> int:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO extracted_pages
                (source_document_id, page_number, text, extraction_method, char_count)
            VALUES
                (:source_document_id, :page_number, :text, :extraction_method, :char_count)
            ON CONFLICT(source_document_id, page_number) DO UPDATE SET
                text=excluded.text,
                extraction_method=excluded.extraction_method,
                char_count=excluded.char_count
            """,
            asdict(record),
        )
        row = conn.execute(
            "SELECT id FROM extracted_pages WHERE source_document_id = ? AND page_number = ?",
            (record.source_document_id, record.page_number),
        ).fetchone()
        return row["id"]


def get_pages_for_document(source_document_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM extracted_pages WHERE source_document_id = ? ORDER BY page_number",
            (source_document_id,),
        ).fetchall()


def count_pages_for_document(source_document_id: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM extracted_pages WHERE source_document_id = ?",
            (source_document_id,),
        ).fetchone()
        return row["c"]
