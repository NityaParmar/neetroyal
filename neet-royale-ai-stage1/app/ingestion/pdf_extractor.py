"""
Stage 2: Extract raw text from every downloaded PDF, page by page.

Run directly:
    python -m app.ingestion.pdf_extractor

For each page:
  1. Try pulling text straight from the PDF's embedded text layer (PyMuPDF).
     Fast and accurate — works if the PDF was generated digitally.
  2. If that comes back near-empty (common with scanned/photographed
     question papers, where the "text" is actually just an image), fall
     back to OCR: rasterize the page to an image and run Tesseract on it.

OCR requires two things NOT installed via pip alone:
  - Tesseract OCR engine:   https://github.com/UB-Mannheim/tesseract/wiki
    (Windows installer — after installing, note the install path, usually
    C:\\Program Files\\Tesseract-OCR\\tesseract.exe)
  - Poppler (for pdf2image): https://github.com/oschwartz10612/poppler-windows/releases
    (unzip anywhere, add its /bin folder to your PATH)

If neither is installed, native-text extraction still works fine — OCR
only kicks in for pages that need it, and those get marked 'needs_ocr'
in the logs instead of crashing the whole run.
"""

import logging
from pathlib import Path

import pymupdf as fitz  # PyMuPDF — new import name (old `import fitz` is deprecated)

from app.db.page_registry import ExtractedPageRecord, init_db, upsert_page
from app.db.source_registry import list_source_documents

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# A page with fewer than this many extracted characters is treated as
# "probably scanned" and routed to OCR instead.
NATIVE_TEXT_MIN_CHARS = 20

# OCR dependencies are optional — imported lazily so this module still
# works for people who haven't installed Tesseract/Poppler yet.
_OCR_AVAILABLE = True
try:
    import pytesseract
    from pdf2image import convert_from_path
except ImportError:
    _OCR_AVAILABLE = False


def _extract_native_text(page: fitz.Page) -> str:
    return page.get_text().strip()


def _extract_via_ocr(pdf_path: Path, page_number: int) -> str | None:
    """page_number is 1-indexed to match PyMuPDF's page.number + 1 convention
    used elsewhere in this file."""
    if not _OCR_AVAILABLE:
        logger.warning(
            "Page %d of %s looks scanned but OCR deps aren't installed "
            "(pip install pytesseract pdf2image, plus Tesseract + Poppler "
            "binaries — see module docstring). Skipping OCR for this page.",
            page_number, pdf_path.name,
        )
        return None

    try:
        images = convert_from_path(
            str(pdf_path), first_page=page_number, last_page=page_number, dpi=300
        )
        if not images:
            return None
        return pytesseract.image_to_string(images[0]).strip()
    except Exception as exc:
        logger.error("OCR failed on page %d of %s: %s", page_number, pdf_path.name, exc)
        return None


def extract_document(source_document_id: int, pdf_path: Path) -> dict[str, int]:
    """Extracts every page of one PDF and stores it. Returns a summary count."""
    summary = {"native": 0, "ocr": 0, "failed": 0}

    doc = fitz.open(str(pdf_path))
    try:
        for page_index in range(len(doc)):
            page_number = page_index + 1  # 1-indexed for humans / DB
            page = doc[page_index]

            native_text = _extract_native_text(page)

            if len(native_text) >= NATIVE_TEXT_MIN_CHARS:
                method = "native"
                text = native_text
            else:
                ocr_text = _extract_via_ocr(pdf_path, page_number)
                if ocr_text:
                    method = "ocr"
                    text = ocr_text
                else:
                    summary["failed"] += 1
                    logger.warning(
                        "No usable text for page %d of %s (native and OCR both empty/unavailable)",
                        page_number, pdf_path.name,
                    )
                    continue

            upsert_page(
                ExtractedPageRecord(
                    source_document_id=source_document_id,
                    page_number=page_number,
                    text=text,
                    extraction_method=method,
                    char_count=len(text),
                )
            )
            summary[method] += 1
    finally:
        doc.close()

    return summary


def extract_all() -> None:
    init_db()
    documents = list_source_documents(status="downloaded")

    if not documents:
        logger.warning("No downloaded source documents found — run Stage 1 ingestion first.")
        return

    for doc_row in documents:
        pdf_path = Path(doc_row["local_path"])
        if not pdf_path.exists():
            logger.error("Registered path missing on disk for %s: %s", doc_row["name"], pdf_path)
            continue

        logger.info("Extracting %s (%s)...", doc_row["name"], pdf_path)
        summary = extract_document(doc_row["id"], pdf_path)
        logger.info(
            "%s done: %d native, %d OCR, %d failed",
            doc_row["name"], summary["native"], summary["ocr"], summary["failed"],
        )


if __name__ == "__main__":
    extract_all()
