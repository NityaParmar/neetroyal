from app.db.page_registry import get_pages_for_document
from app.db.source_registry import list_source_documents

print("--- All source documents (any status) ---")
for doc in list_source_documents():
    print(doc["name"], "|", doc["status"])

print()
print("--- Sample OCR text from NEET_2022, page 1 (id=3) ---")
pages = get_pages_for_document(3)
if pages:
    print(pages[0]["text"][:500])
else:
    print("(no pages found for id=3 -- check the id matches your NEET_2022 entry above)")
