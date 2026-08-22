"""
Stage 5: RAG-based gap-fill question generation.

Run directly:
    python -m app.rag.generator

Only runs when Stage 4 (embedder.py) detects topics that are
under-represented in the question bank (< MIN_QUESTIONS_PER_TOPIC).
For each gap:
  1. find_similar() is used to retrieve the closest existing questions as
     few-shot context for the generation prompt.
  2. The Groq/Qwen model generates one new MCQ for that topic.
  3. The new question is inserted into the question bank with:
       source_url  = "generated"
       source_type = "generated"   (tagged so the summary is honest about origin)
       confidence  = 0.0           (generated, not sourced — always flag for review)

Questions tagged source_type='generated' are served during matches just
like extracted ones, but the performance summary shows them with a
"Generated (not from a past paper)" label instead of a real link.
"""

import json
import logging
import os
import re
import time

from dotenv import load_dotenv
from groq import Groq

from app.db.question_registry import QuestionRecord, count_questions, init_db, insert_question
from app.db.source_registry import list_source_documents
from app.rag.embedder import find_similar, topic_gap_subjects

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

GROQ_MODEL = "qwen/qwen3.6-27b"
GENERATED_SOURCE_URL = "generated"
# Synthetic source_document_id used for all generated questions.
# We reserve id=0 by convention (registry auto-increment starts at 1).
GENERATED_SOURCE_DOC_ID = 0

GAP_FILL_SYSTEM_PROMPT = """You are an expert NEET (Indian medical entrance exam) question author.
You will be given:
- A subject and topic that needs more practice questions
- A few example questions already in the bank (for style/difficulty reference)

Your task: write exactly ONE new multiple-choice question on that topic, at NEET difficulty.

Rules:
- 4 options (A, B, C, D) — only one is correct
- The question must NOT duplicate any of the examples provided
- Include a factually correct answer with your highest confidence
- Keep language concise, exam-style

Respond with ONLY a JSON object (no markdown fences, no explanation):
{
  "question_text": "...",
  "option_a": "...",
  "option_b": "...",
  "option_c": "...",
  "option_d": "...",
  "correct_answer": "A" | "B" | "C" | "D",
  "topic": "..."
}"""


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _get_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set in .env")
    return Groq(api_key=api_key)


def _generate_one(client: Groq, subject: str, topic: str, examples: list[dict]) -> dict | None:
    """Calls the LLM to generate a single gap-fill question. Returns parsed dict or None."""
    example_block = "\n".join(
        f"- {ex['topic']}: {ex.get('question_text', '')}" for ex in examples[:3]
    ) or "(no examples available yet)"

    user_msg = (
        f"Subject: {subject}\n"
        f"Topic: {topic}\n\n"
        f"Example questions already in the bank:\n{example_block}\n\n"
        "Now write ONE new question for this topic."
    )

    for attempt in range(1, 4):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": GAP_FILL_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.7,
                max_completion_tokens=800,
                reasoning_format="parsed",
            )
            raw = _strip_think(response.choices[0].message.content)
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
            return json.loads(raw)
        except Exception as exc:
            is_rate = "rate_limit" in str(exc) or "429" in str(exc)
            wait = 65 if is_rate else 2
            logger.warning("Gap-fill attempt %d/3 failed: %s (waiting %ds)", attempt, exc, wait)
            time.sleep(wait)
    return None


def fill_gaps(target_per_topic: int = 5) -> int:
    """
    Generates questions for every under-represented topic until each has
    at least `target_per_topic` examples. Returns total questions generated.
    """
    init_db()
    client = _get_client()
    gaps = topic_gap_subjects(min_count=target_per_topic)

    if not gaps:
        logger.info("No topic gaps found — question bank is well-covered.")
        return 0

    logger.info("%d topics need gap-fill generation.", len(gaps))
    total_generated = 0

    for gap in gaps:
        subject = gap["subject"]
        topic = gap["topic"]
        current_count = gap["count"]
        needed = target_per_topic - current_count

        logger.info(
            "Generating %d question(s) for [%s] %s (currently %d)",
            needed, subject, topic, current_count,
        )

        # Retrieve similar existing questions as few-shot context
        similar = find_similar(f"{subject} {topic}", top_k=3)

        for _ in range(needed):
            result = _generate_one(client, subject, topic, similar)
            if result is None:
                logger.error("Generation failed for topic: %s", topic)
                break

            # Validate minimal shape
            required_keys = {"question_text", "option_a", "option_b", "option_c",
                             "option_d", "correct_answer", "topic"}
            if not required_keys.issubset(result.keys()):
                logger.warning("Generated question missing keys — skipping: %s", result)
                continue

            answer = result["correct_answer"].strip().upper()
            if answer not in {"A", "B", "C", "D"}:
                logger.warning("Invalid correct_answer %r — skipping", answer)
                continue

            record = QuestionRecord(
                source_document_id=GENERATED_SOURCE_DOC_ID,
                page_number=0,
                question_text=result["question_text"].strip(),
                option_a=result["option_a"].strip(),
                option_b=result["option_b"].strip(),
                option_c=result["option_c"].strip(),
                option_d=result["option_d"].strip(),
                correct_answer=answer,
                subject=subject,
                topic=result.get("topic", topic).strip(),
                confidence=0.0,   # generated — always flag for review
            )
            insert_question(record)
            total_generated += 1
            time.sleep(1)  # TPM breathing room

    logger.info("Gap-fill complete: %d questions generated.", total_generated)
    return total_generated


if __name__ == "__main__":
    n = fill_gaps()
    print(f"Generated {n} questions to fill topic gaps.")
