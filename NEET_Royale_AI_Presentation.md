# NEET Royale AI Microservice
## Technical Presentation & Integration Guide

---

## 1. What Is This?

**NEET Royale** is a multiplayer quiz battle platform where students compete in real-time by answering NEET (National Eligibility cum Entrance Test) exam questions. This microservice is the **AI brain** behind the quiz — it sources real past-paper questions, serves them during matches, tracks every answer, and delivers a detailed performance report when the round ends.

> This is a **standalone FastAPI microservice** — it has no frontend of its own.  
> It exposes REST endpoints consumed by your backend gateway and surfaced to players through your frontend.

---

## 2. Why Was It Built This Way?

### The Core Design Decision: Extract Real Questions First

Rather than generating questions from scratch using an AI model (which risks hallucinated facts in a high-stakes medical entrance exam context), this system uses a **Phase 1: Extract → Phase 2: Fill Gaps** strategy:

| Approach | Problem | Our Choice |
|---|---|---|
| Pure AI generation | Hallucinated facts, no citation | ❌ |
| Manual curation | Doesn't scale, expensive | ❌ |
| Extract from real papers + RAG gap-fill | Accurate, citable, scalable | ✅ |

Every question can be traced back to its **source paper and page number** — so when a student finishes a match, they see *exactly which NTA paper* each question came from and can go review it.

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   NEET Royale AI Microservice                │
│                                                             │
│  ┌──────────────┐    ┌─────────────────┐    ┌───────────┐  │
│  │  Question    │    │   FastAPI REST   │    │  Match    │  │
│  │  Bank DB     │◄───│   Endpoints     │───►│  Perf DB  │  │
│  │ (registry.db)│    │  (4 routes)     │    │(perf.db)  │  │
│  └──────────────┘    └─────────────────┘    └───────────┘  │
│         ▲                    ▲                              │
│         │                    │                              │
│  ┌──────────────┐    ┌────────────────┐                     │
│  │  5-Stage     │    │  FAISS Vector  │                     │
│  │  Pipeline    │    │  Index         │                     │
│  │  (offline)   │    │ (embeddings)   │                     │
│  └──────────────┘    └────────────────┘                     │
└─────────────────────────────────────────────────────────────┘
         ▲                              ▲
         │ HTTP REST                    │ HTTP REST
┌────────┴────────┐           ┌────────┴────────┐
│  Backend        │           │  Frontend       │
│  Gateway        │           │  (optional      │
│  (teammates)    │           │   direct calls) │
└─────────────────┘           └─────────────────┘
```

### Two Separate Databases

| Database | File | Tables | Purpose |
|---|---|---|---|
| **Question Bank** | `data/registry.db` | `source_documents`, `extracted_pages`, `questions` | Built offline by the pipeline. Read-only at runtime. |
| **Match Performance** | `data/performance.db` | `match_sessions`, `match_answers` | Written at runtime as players answer questions. |

Keeping them separate means you can wipe or rebuild the question bank without touching any player match history.

---

## 4. The 5-Stage Offline Pipeline

This pipeline runs **once** (or whenever you add new source papers). It populates the question bank before the API starts serving.

```
PDF Files
   │
   ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 1: Source Registration                           │
│  downloader.py                                          │
│  • reads sources.py (list of papers + their URLs)       │
│  • detects manually-saved PDFs in data/raw_pdfs/        │
│  • registers each: name, source_url, sha256 hash        │
│  • stores in registry.db → source_documents             │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 2: PDF Text Extraction                           │
│  pdf_extractor.py                                       │
│  • PyMuPDF for digital PDFs (fast, lossless)            │
│  • Tesseract OCR fallback for scanned/image pages       │
│  • stores per-page raw text in registry.db → extracted_pages │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 3: LLM MCQ Extraction                            │
│  llm_extractor.py                                       │
│  • sends each page to Groq → qwen/qwen3.6-27b           │
│  • model outputs structured JSON: question, 4 options,  │
│    correct answer, subject, topic, confidence           │
│  • strips <think>...</think> blocks (Qwen quirk)        │
│  • stores in registry.db → questions                    │
│  • idempotent: skips already-processed pages            │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 4: Embedding + FAISS Index                       │
│  rag/embedder.py                                        │
│  • embeds all questions using all-MiniLM-L6-v2 (~22MB)  │
│  • builds FAISS flat-L2 index (CPU, no GPU needed)      │
│  • detects topic gaps: topics with < 5 questions        │
│  • saves index to data/faiss_index/                     │
└────────────────────────┬────────────────────────────────┘
                         │ (only if gaps exist)
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 5: RAG Gap-Fill Generation                       │
│  rag/generator.py                                       │
│  • for each under-represented topic:                    │
│    - finds similar existing questions via FAISS         │
│    - uses them as few-shot examples in the prompt       │
│    - generates a new MCQ via Groq                       │
│  • tags generated questions: source_url="generated",   │
│    confidence=0.0 (always flagged for review)           │
│  • inserted into questions table like extracted ones    │
└─────────────────────────────────────────────────────────┘
```

---

## 5. The 4 REST Endpoints (Runtime)

These are what the backend team integrates against. All endpoints are documented at `/docs` (Swagger UI).

---

### `GET /match/questions` — Serve Questions for a Round

**Purpose:** Fetch a set of MCQs to present to players during a live match.

**Query Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `count` | int | 10 | How many questions (1–100) |
| `subject` | string | — | `physics` / `chemistry` / `biology` |
| `min_confidence` | float | 0.0 | Filter out low-confidence questions |

**Response (array of QuestionOut):**
```json
[
  {
    "id": 42,
    "question_text": "Which of the following is the powerhouse of the cell?",
    "option_a": "Nucleus",
    "option_b": "Mitochondria",
    "option_c": "Ribosome",
    "option_d": "Golgi apparatus",
    "subject": "biology",
    "topic": "Cell Biology",
    "source_type": "extracted"
  }
]
```

> [!IMPORTANT]
> `correct_answer` is **intentionally absent** from this response. It is only revealed in `/answers/submit`, preventing clients from reading the answer before they submit.

---

### `POST /answers/submit` — Record a Player's Answer

**Purpose:** Called once per question as the player submits their choice. Returns real-time feedback.

**Request Body:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "player_aditya",
  "match_id": "match_round_7",
  "question_id": 42,
  "chosen_answer": "B"
}
```

**Response:**
```json
{
  "is_correct": true,
  "correct_answer": "B",
  "source_url": "https://docs.aglasem.com/view/fcc6e1ea-...",
  "source_page": 7,
  "question_id": 42
}
```

**How sessions work:**  
No separate "start session" call is needed. The session is **auto-created on the first answer submission** for a `(session_id, user_id, match_id)` triple. Duplicate submissions for the same `(session_id, question_id)` are rejected with HTTP 409.

---

### `GET /performance/summary/{session_id}` — Post-Match Report

**Purpose:** The full breakdown shown to the player after the round ends.

**Response:**
```json
{
  "session_id": "550e8400-...",
  "user_id": "player_aditya",
  "match_id": "match_round_7",
  "started_at": "2024-05-01T10:00:00Z",
  "ended_at": "2024-05-01T10:15:00Z",
  "status": "completed",
  "total_questions": 10,
  "correct": 7,
  "incorrect": 3,
  "score_percent": 70.0,
  "answers": [
    {
      "question_id": 42,
      "question_text": "Which of the following is the powerhouse of the cell?",
      "option_a": "Nucleus",
      "option_b": "Mitochondria",
      "option_c": "Ribosome",
      "option_d": "Golgi apparatus",
      "correct_answer": "B",
      "chosen_answer": "B",
      "is_correct": true,
      "subject": "biology",
      "topic": "Cell Biology",
      "source_url": "https://docs.aglasem.com/view/fcc6e1ea-...",
      "source_page": 7,
      "source_type": "extracted",
      "answered_at": "2024-05-01T10:05:33Z"
    }
  ]
}
```

The `source_url` in each answer is what gets displayed to students as **"Review this topic → [original paper link]"**.

---

### `POST /performance/end/{session_id}` — Close a Session

**Purpose:** Mark the match round as finished. Sets `ended_at` and `status=completed`.

```bash
POST /performance/end/550e8400-e29b-41d4-a716-446655440000
```

```json
{ "session_id": "550e8400-...", "status": "completed" }
```

---

## 6. Component Breakdown

| Component | File(s) | Tech | Role |
|---|---|---|---|
| Source Registry | `db/source_registry.py` | SQLite | Stores PDFs, their URLs, download status |
| Page Store | `db/page_registry.py` | SQLite | Per-page extracted text |
| Question Bank | `db/question_registry.py` | SQLite | All extracted + generated MCQs |
| Performance DB | `db/performance_db.py` | SQLite | Sessions + per-answer records |
| Downloader | `ingestion/downloader.py` | requests | Registers PDFs, skips already-present |
| PDF Extractor | `ingestion/pdf_extractor.py` | PyMuPDF + Tesseract | Native text + OCR fallback |
| LLM Extractor | `extraction/llm_extractor.py` | Groq / Qwen3.6-27b | Structured MCQ extraction |
| Embedder | `rag/embedder.py` | sentence-transformers + FAISS | Vector index, gap detection |
| Gap Generator | `rag/generator.py` | Groq / Qwen3.6-27b | RAG-based MCQ generation |
| Match API | `api/match.py` | FastAPI | Serve questions |
| Answers API | `api/answers.py` | FastAPI | Record answers |
| Performance API | `api/performance.py` | FastAPI | Summaries + session close |
| App Entry | `main.py` | FastAPI + Uvicorn | Wires all routers, CORS, startup |

---

## 7. Data Flow During a Live Match

```
Player's browser
      │
      │  1. GET /match/questions?count=10
      ▼
Backend Gateway ──────────────────────────► AI Microservice
                                                │
                                          reads registry.db
                                          returns 10 questions (no correct_answer)
                                                │
Backend Gateway ◄─────────────────────────────┘
      │
      │  returns questions to frontend
      ▼
Player's browser (shows Question 1)
      │
      │  Player picks "B"
      │
      │  2. POST /answers/submit  {session_id, user_id, match_id, question_id, chosen_answer: "B"}
      ▼
Backend Gateway ──────────────────────────► AI Microservice
                                                │
                                          writes to performance.db
                                          looks up correct_answer
                                          returns {is_correct, correct_answer, source_url}
                                                │
Backend Gateway ◄─────────────────────────────┘
      │
      │  shows "✅ Correct!" / "❌ Wrong, answer was B"
      ▼
      ... (repeat for all questions) ...
      │
      │  3. POST /performance/end/{session_id}
      │  4. GET  /performance/summary/{session_id}
      ▼
Backend Gateway ──────────────────────────► AI Microservice
                                                │
                                          reads all answers from performance.db
                                          returns full report with source links
                                                │
Backend Gateway ◄─────────────────────────────┘
      │
      │  renders post-match results page
      ▼
Player sees: score, each question, what they chose,
             correct answer, topic, and link to source paper
```

---

## 8. Backend Integration Guide

### Base URL
```
http://<ai-microservice-host>:8000
```

### CORS
All origins are allowed by default during development. For production, restrict this in `app/main.py`:
```python
allow_origins=["https://your-gateway-domain.com"]
```

### Session ID Strategy
The gateway is responsible for generating session IDs. Use UUID v4:
```python
import uuid
session_id = str(uuid.uuid4())   # one per user per match round
```

### Recommended Gateway Workflow

```python
# At match start: fetch questions
questions = GET /match/questions?count=10&subject=biology

# As each player answers (call per question, per player):
result = POST /answers/submit {
  session_id: <uuid>,         # unique per player per round
  user_id: <your user id>,
  match_id: <your match id>,
  question_id: <from questions list>,
  chosen_answer: "A"          # whatever the player picked
}

# When round timer expires:
POST /performance/end/{session_id}

# To show results page:
summary = GET /performance/summary/{session_id}
```

### Error Codes

| Code | Meaning | Action |
|---|---|---|
| `400` | Invalid `chosen_answer` (not A/B/C/D) or invalid `subject` | Validate on gateway before calling |
| `404` | No questions in bank / session not found | Run the pipeline first; check session_id |
| `409` | Answer already submitted for this question in this session | Idempotency guard — safe to ignore |
| `500` | Internal error | Check server logs |

---

## 9. Frontend Integration Guide

The frontend never calls this microservice directly — all calls go through the **backend gateway**, which forwards requests and adds auth/rate-limiting.

### What the frontend needs to display

**During a match round:**
```
Question card:
  - question_text
  - option_a / option_b / option_c / option_d
  - subject tag + topic label

After each answer (immediate feedback from /answers/submit):
  - ✅ or ❌ indicator
  - Show correct_answer if wrong
```

**Post-match results screen (from /performance/summary):**
```
Score card: X / Y correct (Z%)

Per-question review table:
  Columns: Question | Your Answer | Correct | Topic | Source
  
  "Source" column = clickable link to source_url
    → if source_type = "extracted": shows "📄 NEET 2024 Paper →"
    → if source_type = "generated": shows "🤖 AI Generated"
```

### Sample Results Table (React-style pseudocode)
```jsx
{summary.answers.map(answer => (
  <tr key={answer.question_id}>
    <td>{answer.question_text}</td>
    <td className={answer.is_correct ? "green" : "red"}>
      {answer.chosen_answer}
    </td>
    <td>{answer.correct_answer}</td>
    <td>{answer.topic}</td>
    <td>
      {answer.source_type === "extracted"
        ? <a href={answer.source_url} target="_blank">📄 View Source</a>
        : <span>🤖 AI Generated</span>
      }
    </td>
  </tr>
))}
```

---

## 10. Deployment Checklist

### For backend team cloning this repo:

```bash
# 1. Clone
git clone <repo-url>
cd neet-royale-ai-stage1

# 2. Python environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux
pip install -r requirements.txt

# 3. Environment variables
copy .env.example .env
# Edit .env → GROQ_API_KEY=gsk_...

# 4. Add PDF source papers (see Section 11)

# 5. Run the pipeline (one time)
python -m app.ingestion.downloader        # Stage 1
python -m app.ingestion.pdf_extractor     # Stage 2
python -m app.extraction.llm_extractor    # Stage 3
python -m app.rag.embedder                # Stage 4
python -m app.rag.generator               # Stage 5 (optional)

# 6. Start the API
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Production deployment:
```bash
# Without --reload flag
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Or with Docker (Dockerfile not included yet — ask the AI microservice team to add one):
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 11. Adding Source Papers (How to Grow the Question Bank)

> [!NOTE]
> Most NEET paper sites (AglaSem, Shiksha, NCERT) block scripted downloads. You must download PDFs manually via browser.

**Steps:**
1. Open the `source_url` from `app/ingestion/sources.py` in your browser
2. Download the PDF
3. Save it as `data/raw_pdfs/{name}.pdf` — the `name` must match exactly what's in `sources.py`
4. Re-run Stages 1–4

**To add a new paper, edit `sources.py`:**
```python
SourceDocument(
    name="NEET_2019_FullPaper",           # becomes data/raw_pdfs/NEET_2019_FullPaper.pdf
    source_url="https://...",              # shown to students in performance summary
    subject=Subject.MIXED,
    doc_type=DocType.NTA_OFFICIAL_PAPER,
    year=2019,
),
```

---

## 12. Tech Stack Summary

| Layer | Technology |
|---|---|
| API Framework | FastAPI 0.115 |
| ASGI Server | Uvicorn |
| LLM API | Groq Cloud → qwen/qwen3.6-27b |
| PDF Parsing | PyMuPDF (digital) + Tesseract (OCR) |
| Embeddings | sentence-transformers / all-MiniLM-L6-v2 |
| Vector Search | FAISS CPU |
| Databases | SQLite (two separate files) |
| Validation | Pydantic v2 |
| HTTP Client | requests |
| Python | 3.12+ |

---

## 13. Limitations & Known Constraints

| Constraint | Detail |
|---|---|
| `correct_answer` is LLM-inferred | Not cross-checked against NTA official answer keys. Use `confidence` field to flag low-certainty answers for manual review. |
| SQLite | Fine for development and small scale. For production load, swap to PostgreSQL (schema is identical, just change the connection in each `db/*.py` file). |
| Manual PDF downloads | Bot-protection on NTA/AglaSem sites means PDFs must be downloaded by hand. The downloader handles registration once the file is on disk. |
| Generated questions | Tagged `source_type="generated"` and `confidence=0.0`. Always shown honestly in the performance summary, never disguised as real exam questions. |
| OCR quality | Scanned PDFs produce noisier text. The LLM cleans obvious OCR artifacts but significant noise may reduce extraction quality. |

---

*NEET Royale AI Microservice — built for the NEET Royale multiplayer quiz platform.*  
*Questions sourced from NTA official papers (2020–2024). All source attributions preserved.*
