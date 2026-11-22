# Handoff: where SpeakWell stands (2026-11-22)

Read this first in a new chat. For how the code works, see `docs/LEARN.md`.

## State
- SpeakWell is a local mock-interview app: coding (Python), system design,
  behavioral, and resume deep dive. Tracks: SWE, AI/ML, Cybersecurity.
  Levels: Intern, New grad.
- v2 is **turn-based voice**: you press to talk (Space / ⌘↵), each answer is
  transcribed in English, Gemini 3.8 Flash writes the reply (Flash-Lite for the
  intro and closing), the server validates it, and Chrome reads it aloud.
- v1 used Gemini Live (real-time voice). It was dropped because it switched to
  Chinese, interrupted thinking pauses, went off topic, and cost about $1.60
  per 45 minutes. See the "v2" section in
  `docs/design/specs/2026-11-20-speakwell-interview-revamp-design.md`.
- Planner and grader: Gemini 4 Argon. Budget guard: $10/month (Google AI Pro
  credits, paid API key).
- 71 tests pass: `.venv/bin/python -m pytest -q`.
- Run it: `source .venv/bin/activate && python -m uvicorn main:app`, then
  open http://127.0.0.1:8000 in Chrome.

## Open items
1. **Nothing is committed.** All v1 and v2 work is uncommitted on `main`.
   Review it, then commit.
2. **Test interviews in History:** 5 short runs from 2026-11-22 01:35–01:49 UTC
   (scores 4–8, under 90 s each, $0.83 total). Delete them from the History
   page. Keep the real one: 31 min, system design, score 44.
3. **Not yet tried by a human on v2:** how Chrome's voices sound, the answer
   time limits (`ANSWER_LIMIT_S` in `interviewer.py`), and reply speed
   (~2.5 s measured).
4. **Cost estimate to confirm:** about $0.50–0.70 per full 45-minute interview.
   Check the cost shown on a real interview's report.

## User preferences
- Wants realism: the interviewer leads, no feedback until the end, cuts you
  off when you ramble, gives hints that cost points.
- Wants to keep costs low within the $10/month of credits, without losing
  quality. Keep Argon for grading.
- Wants to learn the system: walkthroughs and quizzes (`docs/LEARN.md`).
- The API key stays in `.env` (no Keychain).
