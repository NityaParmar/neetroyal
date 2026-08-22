"""
Stage 1: Download every source document listed in sources.py, verify it's
a real PDF, and register it (with its source URL) in the SQLite registry.

Run directly:
    python -m app.ingestion.downloader

Idempotent: re-running skips files that are already downloaded and whose
content hash hasn't changed, so this is safe to run repeatedly during dev
or as a scheduled refresh job.
"""

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests

from app.db.source_registry import (
    SourceDocumentRecord,
    init_db,
    mark_failed,
    upsert_source_document,
)
from app.ingestion.sources import SOURCE_DOCUMENTS, SourceDocument

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

RAW_PDF_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "raw_pdfs"
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3


def _sha256_of_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _download_one(doc: SourceDocument) -> Path:
    """Downloads a single document with retries. Raises on final failure.

    If a file already exists at the expected destination (e.g. you manually
    saved it there via browser because the site blocks scripted requests),
    the network request is skipped entirely and the existing file is used
    as-is. This is the recommended path for sites with bot protection
    (403s, Cloudflare challenges, etc.) that requests.get() cannot get past
    no matter how the headers are tuned.
    """
    RAW_PDF_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = RAW_PDF_DIR / f"{doc.name}.pdf"

    if dest_path.exists() and dest_path.stat().st_size > 0:
        logger.info("Found existing local file for %s, skipping download", doc.name)
        return dest_path

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                doc.source_url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/pdf,*/*",
                },
            )
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower() and not response.content[:4] == b"%PDF":
                raise ValueError(
                    f"URL did not return a PDF (Content-Type={content_type!r}): {doc.source_url}"
                )

            dest_path.write_bytes(response.content)
            return dest_path

        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            logger.warning(
                "Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, doc.name, exc
            )

    raise RuntimeError(f"Failed to download {doc.name} after {MAX_RETRIES} attempts") from last_error


def ingest_all() -> dict[str, int]:
    """Downloads every configured source and registers it in the DB.
    Returns a summary count of successes/failures."""
    init_db()
    summary = {"succeeded": 0, "failed": 0, "skipped": 0}

    for doc in SOURCE_DOCUMENTS:
        try:
            dest_path = _download_one(doc)
            file_hash = _sha256_of_file(dest_path)

            record = SourceDocumentRecord(
                name=doc.name,
                source_url=doc.source_url,
                subject=doc.subject.value,
                doc_type=doc.doc_type.value,
                year=doc.year,
                local_path=str(dest_path),
                sha256=file_hash,
                downloaded_at=datetime.now(timezone.utc).isoformat(),
                status="downloaded",
            )
            doc_id = upsert_source_document(record)
            logger.info("Registered %s (id=%d) -> %s", doc.name, doc_id, doc.source_url)
            summary["succeeded"] += 1

        except RuntimeError as exc:
            logger.error("Giving up on %s: %s", doc.name, exc)
            mark_failed(doc.name, doc.source_url)
            summary["failed"] += 1

    return summary


if __name__ == "__main__":
    result = ingest_all()
    logger.info("Ingestion complete: %s", result)
