"""
Match serving endpoint.

GET /match/questions
    Returns N random questions for a match round.
    Query params:
        count   (int, default 10)  — how many questions to return
        subject (str, optional)    — filter by 'physics'|'chemistry'|'biology'
        min_confidence (float, default 0.0) — exclude questions below this threshold

Response shape (list of QuestionOut):
    {
      "id": 42,
      "question_text": "...",
      "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...",
      "subject": "biology",
      "topic": "Human Reproduction",
      "source_type": "extracted" | "generated"
    }

NOTE: correct_answer is intentionally NOT included here — the backend
gateway should not expose it to the client before the answer is submitted.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.db.question_registry import get_random_questions

router = APIRouter(prefix="/match", tags=["match"])

GENERATED_SOURCE_DOC_ID = 0  # matches generator.py convention


class QuestionOut(BaseModel):
    id: int
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    subject: str
    topic: str
    source_type: str  # "extracted" | "generated"


@router.get("/questions", response_model=list[QuestionOut], summary="Serve questions for a match round")
def serve_questions(
    count: Annotated[int, Query(ge=1, le=100, description="Number of questions to return")] = 10,
    subject: Annotated[
        str | None,
        Query(description="Filter by subject: physics | chemistry | biology"),
    ] = None,
    min_confidence: Annotated[
        float,
        Query(ge=0.0, le=1.0, description="Exclude questions with confidence below this value"),
    ] = 0.0,
):
    """Return a random set of MCQs for a match round. Correct answers are omitted."""
    if subject and subject not in {"physics", "chemistry", "biology"}:
        raise HTTPException(status_code=400, detail="subject must be physics, chemistry, or biology")

    rows = get_random_questions(count=count * 3, subject=subject)  # over-fetch, then filter
    if not rows:
        raise HTTPException(status_code=404, detail="No questions found in the bank. Run the pipeline first.")

    # Apply confidence filter and trim to requested count
    filtered = [r for r in rows if r["confidence"] >= min_confidence]
    filtered = filtered[:count]

    if not filtered:
        raise HTTPException(
            status_code=404,
            detail=f"No questions found matching min_confidence={min_confidence}",
        )

    return [
        QuestionOut(
            id=row["id"],
            question_text=row["question_text"],
            option_a=row["option_a"],
            option_b=row["option_b"],
            option_c=row["option_c"],
            option_d=row["option_d"],
            subject=row["subject"],
            topic=row["topic"],
            source_type="generated" if row["source_document_id"] == GENERATED_SOURCE_DOC_ID else "extracted",
        )
        for row in filtered
    ]
