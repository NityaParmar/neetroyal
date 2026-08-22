"""
Schema for a single extracted MCQ.

`confidence` is the model's own self-assessed confidence in the
`correct_answer` field specifically (not the question text, which is
extracted verbatim from the source and needs no guessing). Since answers
are being inferred by the LLM rather than cross-checked against an
official answer key, this field is what lets you flag low-confidence
answers for manual review instead of silently trusting everything.
"""

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class SubjectLabel(str, Enum):
    PHYSICS = "physics"
    CHEMISTRY = "chemistry"
    BIOLOGY = "biology"


class ExtractedQuestion(BaseModel):
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str  # one of "A", "B", "C", "D"
    subject: SubjectLabel
    topic: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("correct_answer")
    @classmethod
    def validate_correct_answer(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in {"A", "B", "C", "D"}:
            raise ValueError(f"correct_answer must be A/B/C/D, got {v!r}")
        return v

    @field_validator("question_text", "option_a", "option_b", "option_c", "option_d", "topic")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("field cannot be blank")
        return v
