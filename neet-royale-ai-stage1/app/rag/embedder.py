"""
Stage 4: Embedding + FAISS index for topic-gap detection.

Run directly:
    python -m app.rag.embedder

What this does:
  1. Pulls every question from the question bank.
  2. Embeds each question's "topic + question_text" using a lightweight
     sentence-transformers model (all-MiniLM-L6-v2, ~22 MB, runs on CPU).
  3. Stores the embeddings in a FAISS flat-L2 index on disk at
     data/faiss_index/ alongside a JSON metadata sidecar so we can map
     FAISS vector IDs back to question IDs.
  4. Exposes topic_gap_subjects() which groups stored questions by topic
     and flags any topic that has fewer than MIN_QUESTIONS_PER_TOPIC
     examples — these gaps trigger Stage 5 RAG generation.

The index is rebuilt from scratch each time this script runs, so it stays
current after new questions are extracted.
"""

import json
import logging
from collections import Counter
from pathlib import Path

import numpy as np

from app.db.question_registry import get_random_questions

logger = logging.getLogger(__name__)

INDEX_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "faiss_index"
INDEX_PATH = INDEX_DIR / "questions.index"
META_PATH = INDEX_DIR / "meta.json"

# Topics with fewer than this many questions are flagged as "gaps" and
# will be handed to Stage 5 for RAG-based generation.
MIN_QUESTIONS_PER_TOPIC = 5

# Lazily imported so this module still loads if the heavy deps aren't there.
_FAISS = None
_MODEL = None


def _get_faiss():
    global _FAISS
    if _FAISS is None:
        try:
            import faiss
            _FAISS = faiss
        except ImportError:
            raise ImportError(
                "faiss-cpu is not installed. Run: pip install faiss-cpu"
            )
    return _FAISS


def _get_model():
    global _MODEL
    if _MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        except ImportError:
            raise ImportError(
                "sentence-transformers is not installed. Run: pip install sentence-transformers"
            )
    return _MODEL


def _embed(texts: list[str]) -> np.ndarray:
    """Returns a float32 numpy array of shape (N, D)."""
    model = _get_model()
    vectors = model.encode(texts, show_progress_bar=True, batch_size=32)
    return np.array(vectors, dtype="float32")


def build_index() -> None:
    """Rebuilds the FAISS index from the current question bank. Idempotent."""
    faiss = _get_faiss()
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    # Pull all questions (no subject filter — one combined index)
    rows = get_random_questions(count=999_999)  # effectively "all"
    if not rows:
        logger.warning("No questions in the question bank — run Stages 1-3 first.")
        return

    # Build text representations and metadata
    texts: list[str] = []
    meta: list[dict] = []
    for row in rows:
        texts.append(f"{row['topic']} | {row['question_text']}")
        meta.append({
            "question_id": row["id"],
            "subject": row["subject"],
            "topic": row["topic"],
            "source_document_id": row["source_document_id"],
        })

    logger.info("Embedding %d questions...", len(texts))
    vectors = _embed(texts)

    dim = vectors.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(vectors)

    faiss.write_index(index, str(INDEX_PATH))
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    logger.info("FAISS index built: %d vectors, dim=%d -> %s", len(texts), dim, INDEX_PATH)


def find_similar(query_text: str, top_k: int = 5) -> list[dict]:
    """Nearest-neighbour lookup — used by Stage 5 to find relevant context
    questions when generating a gap-fill MCQ."""
    faiss = _get_faiss()

    if not INDEX_PATH.exists():
        raise FileNotFoundError(
            "FAISS index not found. Run `python -m app.rag.embedder` first."
        )

    index = faiss.read_index(str(INDEX_PATH))
    meta = json.loads(META_PATH.read_text())

    vec = _embed([query_text])
    _, idx_array = index.search(vec, top_k)

    results = []
    for idx in idx_array[0]:
        if 0 <= idx < len(meta):
            results.append(meta[idx])
    return results


def topic_gap_subjects(min_count: int = MIN_QUESTIONS_PER_TOPIC) -> list[dict]:
    """
    Returns a list of {subject, topic, count} dicts for every topic that
    has fewer than `min_count` questions in the bank.

    Stage 5 iterates over this list and generates one or more gap-fill
    MCQs per topic until the gap is closed.
    """
    if not META_PATH.exists():
        logger.warning("FAISS meta not found — returning empty gap list.")
        return []

    meta = json.loads(META_PATH.read_text())
    # Count questions per (subject, topic) pair
    counter: Counter = Counter()
    subject_map: dict[tuple, str] = {}
    for item in meta:
        key = (item["subject"], item["topic"])
        counter[key] += 1
        subject_map[key] = item["subject"]

    gaps = []
    for (subject, topic), count in counter.items():
        if count < min_count:
            gaps.append({"subject": subject, "topic": topic, "count": count})

    gaps.sort(key=lambda g: g["count"])  # worst gaps first
    return gaps


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    build_index()
    gaps = topic_gap_subjects()
    if gaps:
        print(f"\n{len(gaps)} under-represented topics (< {MIN_QUESTIONS_PER_TOPIC} questions):")
        for g in gaps[:20]:
            print(f"  [{g['subject']}] {g['topic']}: {g['count']} questions")
    else:
        print("No topic gaps found — bank looks well-covered.")
