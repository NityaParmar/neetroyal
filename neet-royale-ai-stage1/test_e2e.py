import requests
import json
import uuid

BASE = "http://localhost:8000"
session_id = str(uuid.uuid4())
user_id = "test_player"
match_id = "test_match_001"

# 1. Health check
r = requests.get(f"{BASE}/health")
print("HEALTH:", r.json())

# 2. Fetch 5 questions
r = requests.get(f"{BASE}/match/questions", params={"count": 5})
questions = r.json()
print(f"\nMATCH QUESTIONS ({len(questions)} returned):")
for q in questions:
    subj = q["subject"]
    qid = q["id"]
    txt = q["question_text"][:60].encode("ascii", errors="replace").decode("ascii")
    src = q["source_type"]
    print(f"  [{subj}] id={qid} src={src} | {txt}...")

# 3. Submit answers for all 5 questions
print("\nSUBMITTING ANSWERS:")
for q in questions:
    payload = {
        "session_id": session_id,
        "user_id": user_id,
        "match_id": match_id,
        "question_id": q["id"],
        "chosen_answer": "A",
    }
    r = requests.post(f"{BASE}/answers/submit", json=payload)
    result = r.json()
    correct = result["correct_answer"]
    is_c = result["is_correct"]
    src_url = result["source_url"][:70]
    print(f"  Q{q['id']}: chose=A  correct={correct}  is_correct={is_c}  source={src_url}")

# 4. End session
r = requests.post(f"{BASE}/performance/end/{session_id}")
print("\nEND SESSION:", r.json())

# 5. Performance summary
r = requests.get(f"{BASE}/performance/summary/{session_id}")
summary = r.json()
total = summary["total_questions"]
correct = summary["correct"]
wrong = summary["incorrect"]
pct = summary["score_percent"]
status = summary["status"]
print(f"\nPERFORMANCE SUMMARY:")
print(f"  total={total}  correct={correct}  incorrect={wrong}  score={pct}%  status={status}")

a = summary["answers"][0]
topic = a["topic"]
stype = a["source_type"]
surl = a["source_url"][:70]
print(f"\n  First answer detail:")
print(f"    topic      = {topic}")
print(f"    source_type= {stype}")
print(f"    source_url = {surl}")
