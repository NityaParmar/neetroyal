"""
Performance summary endpoint.

GET /performance/summary/{session_id}
    Returns the full post-match breakdown for one player session:
    every question answered, what they chose, whether it was correct,
    and the source link for the question.

Response shape:
    {
      "session_id": "...",
      "user_id": "...",
      "match_id": "...",
      "started_at": "2024-...",
      "ended_at": "2024-..." | null,
      "status": "active" | "completed",
      "total_questions": 10,
      "correct": 7,
      "incorrect": 3,
      "score_percent": 70.0,
      "answers": [
        {
          "question_id": 42,
          "question_text": "...",
          "option_a": "...", ...,
          "correct_answer": "B",
          "chosen_answer": "A",
          "is_correct": false,
          "subject": "biology",
          "topic": "Human Reproduction",
          "source_url": "https://...",     <- the citation shown to the user
          "source_page": 7,               <- null for generated questions
          "source_type": "extracted" | "generated",
          "answered_at": "2024-..."
        },
        ...
      ]
    }

POST /performance/end/{session_id}
    Marks a session as completed (sets ended_at). Call this when the
    match round finishes. Subsequent /summary calls will show status=completed.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.performance_db import end_session, get_answers_for_session, get_session, init_db

router = APIRouter(prefix="/performance", tags=["performance"])

init_db()

GENERATED_SOURCE_DOC_ID = 0


class AnswerDetail(BaseModel):
    question_id: int
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str
    chosen_answer: str
    is_correct: bool
    subject: str
    topic: str
    source_url: str
    source_page: int | None
    source_type: str  # "extracted" | "generated"
    answered_at: str


class PerformanceSummary(BaseModel):
    session_id: str
    user_id: str
    match_id: str
    started_at: str
    ended_at: str | None
    status: str
    total_questions: int
    correct: int
    incorrect: int
    score_percent: float
    answers: list[AnswerDetail]


@router.get(
    "/summary/{session_id}",
    response_model=PerformanceSummary,
    summary="Get post-match performance summary for a session",
)
def get_summary(session_id: str):
    """
    Full per-question breakdown with correct/incorrect status and source links.
    This is the main output shown to users after a match round ends.
    """
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    answer_rows = get_answers_for_session(session_id)

    answers: list[AnswerDetail] = []
    correct_count = 0

    for row in answer_rows:
        is_correct = bool(row["is_correct"])
        if is_correct:
            correct_count += 1

        source_type = "generated" if row["source_url"] == "generated" else "extracted"

        answers.append(
            AnswerDetail(
                question_id=row["question_id"],
                question_text=row["question_text"],
                option_a=row["option_a"],
                option_b=row["option_b"],
                option_c=row["option_c"],
                option_d=row["option_d"],
                correct_answer=row["correct_answer"],
                chosen_answer=row["chosen_answer"],
                is_correct=is_correct,
                subject=row["subject"],
                topic=row["topic"],
                source_url=row["source_url"],
                source_page=row["source_page"],
                source_type=source_type,
                answered_at=row["answered_at"],
            )
        )

    total = len(answers)
    incorrect_count = total - correct_count
    score_pct = round((correct_count / total * 100), 2) if total > 0 else 0.0

    return PerformanceSummary(
        session_id=session_id,
        user_id=session["user_id"],
        match_id=session["match_id"],
        started_at=session["started_at"],
        ended_at=session["ended_at"],
        status=session["status"],
        total_questions=total,
        correct=correct_count,
        incorrect=incorrect_count,
        score_percent=score_pct,
        answers=answers,
    )


@router.post(
    "/end/{session_id}",
    summary="Mark a match session as completed",
)
def end_match_session(session_id: str):
    """
    Call this when the match round ends. Sets ended_at and status=completed.
    Idempotent — safe to call multiple times.
    """
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    end_session(session_id)
    return {"session_id": session_id, "status": "completed"}
