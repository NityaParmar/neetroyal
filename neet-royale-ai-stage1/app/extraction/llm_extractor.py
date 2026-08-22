"""
Stage 3: Extract structured MCQs from raw page text using Groq-hosted Qwen.

Run directly:
    python -m app.extraction.llm_extractor

Requires GROQ_API_KEY in your .env file (project root).

Idempotent: pages that already have questions in the DB are skipped, so
this is safe to re-run (e.g. after fixing a bug) without creating
duplicate questions or re-spending API calls on pages already done.

IMPORTANT CAVEAT: correct_answer is inferred by the LLM, not checked
against an official NTA answer key (none was ingested). Each question
carries a `confidence` score for exactly this reason — check
get_low_confidence_questions() in question_registry.py before trusting
low-confidence answers in a scored match.
"""

import json
import logging
import os
import re
import time

from dotenv import load_dotenv
from groq import Groq
from pydantic import ValidationError

from app.db.page_registry import get_pages_for_document
from app.db.question_registry import (
    QuestionRecord,
    has_questions_for_page,
    init_db as init_questions_db,
    insert_question,
)
from app.db.source_registry import list_source_documents
from app.models.question import ExtractedQuestion

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

GROQ_MODEL = "qwen/qwen3.6-27b"
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2
# Pages with less text than this aren't worth sending to the LLM (title
# pages, instructions, near-blank pages) — saves API calls.
MIN_PAGE_CHARS_TO_PROCESS = 100

SYSTEM_PROMPT = """You are an exam question extraction engine for a NEET (Indian medical entrance exam) prep platform.

You will be given raw text extracted from one page of a real NEET question paper. Your job:

1. Identify every COMPLETE multiple-choice question on this page (question stem + exactly 4 options). Skip any question that is clearly cut off (started on this page but options are missing, or started on a previous page).
2. For each complete question, determine the correct answer using your own subject knowledge of NEET-level Physics, Chemistry, and Biology. Rate your own confidence in that answer from 0.0 (guessing) to 1.0 (certain).
3. Classify the subject (physics/chemistry/biology) and a short topic label (e.g. "Thermodynamics", "Organic Chemistry - Alkenes", "Human Reproduction").
4. Clean up obvious OCR noise in the question/option text (fix broken words, stray characters) but do NOT change the actual meaning or wording.

Respond with ONLY a JSON array, no other text, no markdown code fences, no explanation. Each element:
{
  "question_text": "...",
  "option_a": "...",
  "option_b": "...",
  "option_c": "...",
  "option_d": "...",
  "correct_answer": "A" | "B" | "C" | "D",
  "subject": "physics" | "chemistry" | "biology",
  "topic": "...",
  "confidence": 0.0-1.0
}

If this page has no complete questions, respond with an empty array: []
"""


def strip_think_block(text: str) -> str:
    """Removes <think>...</think> reasoning blocks that Qwen models emit
    before their actual answer."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _get_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY not found. Create a .env file in the project root with:\n"
            "GROQ_API_KEY=your_key_here"
        )
    return Groq(api_key=api_key)


def _call_llm(client: Groq, page_text: str) -> str:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": page_text},
                ],
                temperature=0.1,  # low temperature: this is extraction, not creative generation
                max_completion_tokens=4000,  # kept under Groq's free-tier 8000 TPM limit alongside prompt tokens
                reasoning_format="parsed",  # keeps <think> reasoning in its own field, message.content is just the final answer
            )
            return response.choices[0].message.content
        except Exception as exc:
            last_error = exc
            is_rate_limit = "rate_limit_exceeded" in str(exc) or "429" in str(exc) or "413" in str(exc)
            delay = 65 if is_rate_limit else RETRY_DELAY_SECONDS  # TPM window resets every 60s
            logger.warning(
                "LLM call attempt %d/%d failed (%s): %s -- waiting %ds before retry",
                attempt, MAX_RETRIES, "rate limit" if is_rate_limit else "error", exc, delay,
            )
            time.sleep(delay)
    raise RuntimeError(f"LLM call failed after {MAX_RETRIES} attempts") from last_error


def _parse_questions(raw_response: str) -> list[ExtractedQuestion]:
    cleaned = strip_think_block(raw_response)

    # Defensive: strip markdown fences if the model added them despite instructions
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned.strip())

    try:
        raw_items = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse LLM response as JSON: %s\nRaw response: %s", exc, cleaned[:500])
        return []

    if not isinstance(raw_items, list):
        logger.error("Expected a JSON array, got %s", type(raw_items))
        return []

    questions = []
    for item in raw_items:
        try:
            questions.append(ExtractedQuestion(**item))
        except ValidationError as exc:
            logger.warning("Skipping invalid question item: %s\nItem: %s", exc, item)

    return questions


def process_page(client: Groq, source_document_id: int, page_number: int, page_text: str) -> int:
    """Extracts and stores questions from one page. Returns count stored."""
    raw_response = _call_llm(client, page_text)
    questions = _parse_questions(raw_response)

    if len(questions) == 0:
        # Helps diagnose whether a 0-result page is genuinely content-light
        # (title page, instructions, diagrams) or something going wrong in
        # parsing — shows exactly what the model returned.
        logger.info(
            "Page %d returned 0 questions. Raw LLM response (first 300 chars): %s",
            page_number, strip_think_block(raw_response)[:300],
        )

    for q in questions:
        insert_question(
            QuestionRecord(
                source_document_id=source_document_id,
                page_number=page_number,
                question_text=q.question_text,
                option_a=q.option_a,
                option_b=q.option_b,
                option_c=q.option_c,
                option_d=q.option_d,
                correct_answer=q.correct_answer,
                subject=q.subject.value,
                topic=q.topic,
                confidence=q.confidence,
            )
        )

    return len(questions)


def extract_all() -> None:
    init_questions_db()
    client = _get_client()

    documents = list_source_documents(status="downloaded")
    if not documents:
        logger.warning("No downloaded source documents found — run Stage 1 first.")
        return

    for doc in documents:
        pages = get_pages_for_document(doc["id"])
        if not pages:
            logger.warning("No extracted pages for %s — run Stage 2 first.", doc["name"])
            continue

        total_questions = 0
        for page in pages:
            if has_questions_for_page(doc["id"], page["page_number"]):
                continue  # already processed in a prior run

            if page["char_count"] < MIN_PAGE_CHARS_TO_PROCESS:
                continue  # not enough text to be worth an API call

            try:
                count = process_page(client, doc["id"], page["page_number"], page["text"])
                total_questions += count
                logger.info(
                    "%s page %d: extracted %d question(s)",
                    doc["name"], page["page_number"], count,
                )
                time.sleep(1)  # small pause between requests to help stay under the free-tier TPM limit
            except RuntimeError as exc:
                logger.error("%s page %d: extraction failed — %s", doc["name"], page["page_number"], exc)

        logger.info("%s complete: %d questions extracted this run", doc["name"], total_questions)


if __name__ == "__main__":
    extract_all()
