# Learning SpeakWell

A guided tour of the code, in the order a request flows through it, followed
by a quiz. Read a section, open the file it names, then try the questions.

## 1. The map

| File | Job | Read first |
|---|---|---|
| `main.py` | HTTP endpoints, security checks, budget guard | `start_interview`, `interview_turn`, `grade_interview` |
| `catalog.py` | Curated topics, phases, rubrics, interviewer styles | `PHASES`, `RUBRICS`, `_pick_weighted` |
| `planner.py` | Turns a topic into a hidden interview plan | `build_prompt`, `_validate`, `build_plan` |
| `interviewer.py` | One interviewer reply per turn, and the rules it must obey | `respond`, `state_text`, `apply_reply`, `_validator` |
| `models.py` | Every Gemini text call, with fallback across models | `generate_json`, `describe_error` |
| `session.py` | One interview's in-memory state | `InterviewSession`, `reveal_for_phase` |
| `grading.py` | Per-answer transcription, then grading at the end | `transcribe_turn`, `grade`, `keep_real_quotes` |
| `pricing.py` | Turns token counts into estimated dollars | `cost_usd`, `cache_cost_usd` |
| `storage.py` | SQLite: interviews, spend log, resume | `save_interview`, `recent_seeds` |
| `audio.py` | ffmpeg in memory | `to_mp3` |
| `static/app.js` | All screens; the `Call` class runs the interview | `Call.startAnswer`, `Call.sendTurn`, `speak` |

## 2. One interview, step by step

1. **Setup → `POST /api/interviews`.** `main.start_interview` checks the
   monthly budget, then calls `planner.build_plan`.
2. **Topic pick.** `catalog.pick_seeds` chooses a curated topic, heavily
   down-weighting ones from your last 10 interviews (`storage.recent_seeds`).
3. **Plan.** The planner model (Argon) writes content only; phases and time
   budgets come from `catalog.PHASES`. `models.generate_json` enforces a JSON
   schema and `planner._validate`; a bad plan falls through to the next model.
4. **Join → `POST /begin`.** Starts the clock and returns the opening line,
   taken straight from the plan (no model call, so it's free and instant).
   Chrome reads it aloud (`speak` in `app.js`).
5. **Your answer.** Press Start answer: the browser records just this answer.
   Press again and it's uploaded to `POST /turn` with the time it started, how
   long it ran, and your current code or notes.
6. **Transcribe.** `grading.transcribe_turn` gets verbatim English words with
   timestamps. They're shifted onto the interview clock and kept in
   `session.words` for grading later.
7. **Reply.** `interviewer.respond` sends three things:
   - the **brief** (persona, rules, full plan): identical every turn, so it's
     stored once in a Google-side cache (`ensure_cache`);
   - the **conversation so far**: append-only;
   - the **state**: clock, phase, next hint, your code, and `DIRECTOR:` lines.
8. **Check and apply.** `_validator` rejects non-English or malformed replies
   (the next model is tried). `apply_reply` enforces the structure: forward
   one phase at a time, no early "your questions", no going back, ending only
   at the end. A phase change can reveal the problem on your screen.
9. **End.** The interviewer ends it, you press End, or the clock runs out.
10. **Grading** (`main._run_grading` → `grading.grade`): voice analysis on your
    answers' audio, filler and pace stats in code, rubric grading by Argon,
    then `keep_real_quotes` drops feedback that quotes things you never said.
11. **Save.** Only scores, feedback and cost go into SQLite.

## 3. Design decisions worth understanding

- **Why not a live voice model?** It decided on its own when you'd finished
  (so it interrupted your thinking pauses), what to say next (so it wandered
  back to earlier topics), and which language to speak. Turn-based, the server
  decides all three and the model only writes the line.
- **Why curated seeds?** Asking for "a random problem" gives the same few
  problems with the same phrasing. A human-picked topic plus "vary the story"
  gives variety with a quality floor.
- **Why is the brief cached but the conversation isn't?** A cache only helps
  for content that's identical across calls. The brief never changes; the
  conversation grows each turn and the state changes completely.
- **Why put the state last?** It's the only part that changes completely each
  turn. Everything before it stays the same from one turn to the next.
- **Why Flash-Lite for the intro and closing?** Small talk doesn't need depth.
  It replies in about 1 second at a fifth of the cost. The hard middle phases
  get Flash.
- **Why transcribe each answer, not the whole recording at the end?** The
  interviewer needs your words to reply anyway. Grading reuses them, so
  nothing is transcribed twice.

## 4. Quiz

Try each one before opening the answer.

<details><summary>1. The model replies in Chinese. What happens before you hear it?</summary>

`interviewer._validator` finds non-Latin characters with `_NON_ENGLISH` and
raises `ModelError`, so `generate_json` tries the next model in the chain.
You never hear the bad reply. Transcription is also pinned to `en-US`.
</details>

<details><summary>2. In the last phase, the model tries to go back to asking about your projects. What stops it?</summary>

Two things. `state_text` adds a DIRECTOR line saying to only answer your
questions and not start new topics. And `apply_reply` ignores any
`next_phase` earlier than the current one, so the phase can't move backward.
</details>

<details><summary>3. Twelve minutes into a 45-minute design interview, the model wants to jump to "your questions". What happens?</summary>

`apply_reply` refuses: the final phase can't start before
`EARLIEST_FINAL_FRACTION` (60%) of the time has passed. `state_text` also tells
it to go deeper instead (follow-ups, edge cases, failure modes).
</details>

<details><summary>4. You pause for 20 seconds mid-answer to think. Does the interviewer jump in?</summary>

No. Nothing is sent until you press Done. Only the per-answer limit
(`ANSWER_LIMIT_S`, e.g. 150 s, or 300 s while coding) stops you. When it does,
the interviewer is told you were cut off and reacts like a real one would.
</details>

<details><summary>5. Your answer was saved, but the reply failed with "busy". What's on screen and what does Retry do?</summary>

`interview_turn` logged your answer before calling the model, then returned
503 with "Retry" in the message. The Retry button calls `/retry`, which asks
for the reply again without re-uploading or re-transcribing your audio.
</details>

<details><summary>6. Why is the coding problem never read aloud?</summary>

When the phase moves to `problem`, `apply_reply` returns the
`reveal_for_phase` payload and the browser shows it, with the function
signature in the editor. The brief tells the interviewer to point at the
screen rather than read the problem out.
</details>

<details><summary>7. How do timestamps in your report line up with what you said?</summary>

Each answer's word times from transcription are shifted by `started_at` (when
you pressed Start, on the interview clock). Grading builds short timestamped
lines from `session.words`, and the grader must quote those lines.
</details>

<details><summary>8. What does a turn cost, and what makes it grow?</summary>

About $0.002 early on, about $0.008 late in a long interview. The cached brief
is cheap; the conversation is re-sent every turn, so cost grows with length.
`MAX_CONVERSATION_CHARS` caps it.
</details>

<details><summary>9. What stops you from overspending?</summary>

Every billable step is written to the `spend` table as it happens
(`session.flush_spend`), including abandoned interviews. `start_interview`
refuses new interviews once this month's total reaches the budget. Google's
own spend cap is the backstop.
</details>

<details><summary>10. Where does your audio go?</summary>

Each answer: browser → server memory → ffmpeg via stdin/stdout → Google
Transcribe (`store=False`). At grading, the joined answers go to Flash-Lite for
voice analysis. Nothing is written to disk. The full-session copy for the
report's player never leaves your browser tab.
</details>

## 5. Small exercises

1. Add a coding topic for the Cybersecurity track in `catalog.py`. Which test
   checks that its id is unique?
2. Make the Tough interviewer cut you off sooner while coding. Which constant
   changes, and which test in `tests/test_interviewer.py` would you update?
3. Add "right" (as in "…, right?") to the soft filler list and write a test in
   `tests/test_grading.py` that a mid-sentence "right" doesn't count.
