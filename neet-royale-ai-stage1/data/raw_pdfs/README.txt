# This folder holds manually downloaded NEET/NCERT PDF source papers.
#
# Files here are intentionally excluded from git (see .gitignore) because:
#   1. PDFs are large binary files (~1–5 MB each)
#   2. Some papers have copyright restrictions
#
# HOW TO POPULATE THIS FOLDER:
#   See README.md → "Adding Source Papers" section.
#   For each SourceDocument in app/ingestion/sources.py:
#     1. Open the source_url in your browser
#     2. Download the PDF
#     3. Save it as:  data/raw_pdfs/{name}.pdf
#        (the `name` field must match exactly, e.g. NEET_2024_FullPaper.pdf)
#     4. Run: python -m app.ingestion.downloader
