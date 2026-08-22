"""
Source registry for NEET Royale question extraction.

WORKFLOW: manual-drop, not live-scrape.
Most of these index pages (AglaSem, Shiksha, NCERT) gate their actual PDF
download behind login/coins/JS, so a scripted download will not reliably
work. Instead:

  1. Open each `source_url` below in your browser.
  2. Download the PDF manually (login/coins if the site requires it).
  3. Save it as data/raw_pdfs/{name}.pdf  (exact `name` field below).
  4. Run `python -m app.ingestion.downloader` — it detects the file
     already exists locally and registers it without touching the network.

`source_url` is still stored and shown to the user later (in the
post-match performance summary, as "where this question came from") —
it's kept even though the download itself is manual.

ONE ENTRY PER PAPER, NOT PER SUBJECT:
Each NEET paper PDF contains Physics + Chemistry + Biology together as one
combined document — there's no separate per-subject file on these sites.
So we register ONE SourceDocument per year/paper (subject=MIXED). Subject
tagging happens later, per-question, in Stage 3 (LLM extraction) — the
model reads each individual question and classifies its subject, rather
than the whole 50-page document being labeled as a single subject.
"""

from dataclasses import dataclass
from enum import Enum


class DocType(str, Enum):
    NTA_OFFICIAL_PAPER = "nta_official_paper"
    NCERT_EXEMPLAR = "ncert_exemplar"


class Subject(str, Enum):
    PHYSICS = "physics"
    CHEMISTRY = "chemistry"
    BIOLOGY = "biology"
    MIXED = "mixed"  # combined paper covering multiple subjects; split at question level in Stage 3


@dataclass(frozen=True)
class SourceDocument:
    name: str            # exact filename expected: data/raw_pdfs/{name}.pdf
    source_url: str      # shown to the user later as "source" — kept even though download is manual
    subject: Subject
    doc_type: DocType
    year: int | None = None


# ---------------------------------------------------------------------------
# One entry per unique paper. Manually download each and save under the
# exact `name` given, e.g. data/raw_pdfs/NEET_2024_FullPaper.pdf
# ---------------------------------------------------------------------------
SOURCE_DOCUMENTS: list[SourceDocument] = [
    SourceDocument(
        name="NEET_2024_FullPaper",
        source_url="https://docs.aglasem.com/view/fcc6e1ea-2f1c-11f0-a4dd-0a5e36bc6706",
        subject=Subject.MIXED,
        doc_type=DocType.NTA_OFFICIAL_PAPER,
        year=2024,
    ),
    SourceDocument(
        name="NEET_2023_FullPaper",
        source_url="https://admission.aglasem.com/neet-2023-question-paper/",
        subject=Subject.MIXED,
        doc_type=DocType.NTA_OFFICIAL_PAPER,
        year=2023,
    ),
    SourceDocument(
        name="NEET_2022_FullPaper",
        source_url="https://admission.aglasem.com/neet-2022-question-paper/",
        subject=Subject.MIXED,
        doc_type=DocType.NTA_OFFICIAL_PAPER,
        year=2022,
    ),
    SourceDocument(
        name="NEET_2021_FullPaper",
        source_url="https://www.shiksha.com/medicine-health-sciences/articles/last-5-years-question-papers-of-neet-ug-pdf-download-blogId-222170",
        subject=Subject.MIXED,
        doc_type=DocType.NTA_OFFICIAL_PAPER,
        year=2021,
    ),
    SourceDocument(
        name="NEET_2020_FullPaper",
        source_url="https://www.shiksha.com/medicine-health-sciences/articles/last-5-years-question-papers-of-neet-ug-pdf-download-blogId-222170",
        subject=Subject.MIXED,
        doc_type=DocType.NTA_OFFICIAL_PAPER,
        year=2020,
    ),
]
