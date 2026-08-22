"""
Quick check: shows native vs OCR page counts per document.
Run: python check_extraction.py
"""

from app.db.source_registry import list_source_documents
from app.db.page_registry import get_pages_for_document

for doc in list_source_documents(status="downloaded"):
    pages = get_pages_for_document(doc["id"])
    native = sum(1 for p in pages if p["extraction_method"] == "native")
    ocr = sum(1 for p in pages if p["extraction_method"] == "ocr")
    print(f"{doc['name']:35s} id={doc['id']:2d}  native={native:3d}  ocr={ocr:3d}  total_extracted={len(pages):3d}")
