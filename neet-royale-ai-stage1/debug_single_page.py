"""
Debug helper: shows the raw page text and the raw (unparsed) LLM response
for ONE page, so we can see why extraction might be returning empty
results. Doesn't write anything to the DB or touch the main pipeline —
safe to run in a second terminal while llm_extractor.py is still going.

Usage: python debug_single_page.py <source_document_id> <page_number>
Example: python debug_single_page.py 1 10
"""

import sys

from app.db.page_registry import get_pages_for_document
from app.extraction.llm_extractor import SYSTEM_PROMPT, _get_client, strip_think_block

if len(sys.argv) != 3:
    print("Usage: python debug_single_page.py <source_document_id> <page_number>")
    sys.exit(1)

doc_id = int(sys.argv[1])
page_num = int(sys.argv[2])

pages = get_pages_for_document(doc_id)
page = next((p for p in pages if p["page_number"] == page_num), None)

if not page:
    print(f"No page {page_num} found for document {doc_id}. Available pages: {[p['page_number'] for p in pages]}")
    sys.exit(1)

print("=" * 60)
print(f"PAGE TEXT (doc={doc_id}, page={page_num}, {page['char_count']} chars, method={page['extraction_method']})")
print("=" * 60)
print(page["text"][:1000])
print("...(truncated)" if len(page["text"]) > 1000 else "")
print()

print("=" * 60)
print("CALLING LLM...")
print("=" * 60)

client = _get_client()
response = client.chat.completions.create(
    model="qwen/qwen3.6-27b",
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": page["text"]},
    ],
    temperature=0.1,
)
raw = response.choices[0].message.content

print("RAW LLM RESPONSE (before stripping <think> blocks):")
print("-" * 60)
print(raw)
print()
print("=" * 60)
print("AFTER strip_think_block():")
print("-" * 60)
print(strip_think_block(raw))
