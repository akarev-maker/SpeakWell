# SpeakWell — Interview Revamp (Design + Architecture Walkthrough)

Status: **built** (2026-11-21). Changes from the draft, decided during the build:
- Keychain support was dropped at your request; the key stays in `.env`.
- Default models assume a paid key (Google AI Pro): Argon plans and grades from text only;
  audio goes to Flash-Lite (tone) and Transcribe (words). See README "Cost".
- A monthly budget guard (default $10) refuses new interviews once estimated spend reaches it.
- The browser only streams your mic while you're speaking, to save Live tokens.
- Transcription is sent with `store=false` (Google otherwise keeps Interactions requests up to 55 days).
- Phase 0's spike confirmed: director notes interrupt the interviewer (~1 s), silent code snapshots
  reach it without triggering speech, and tool calls work on `gemini-3.8-live`.


## v2 (2026-11-22): turn-based voice replaces Gemini Live

After a real 31-minute system design interview, three problems with the live
voice model came up, plus cost:
- It answered in Chinese once (the language was never pinned).
- It treated ~1.2 s of silence as the end of your turn, so it interrupted
  thinking pauses.
- After the candidate's questions it went back to asking about projects. The
  server could only nudge a free-running voice model.
- Cost: $1.12, of which $0.80 was Live (re-billed audio context every turn).

Now: you press to talk. Each answer is transcribed (English pinned, word
timestamps). A text model (Gemini 3.8 Flash; Flash-Lite for intro and closing)
writes the reply from a cached brief, the conversation and a director state.
The server validates it (English only, forward-only phases, no early final
phase, ending only at the end), and Chrome reads it aloud for free. Measured:
~2.5 s per reply, $0.002–0.008 per reply, ~$0.50–0.70 for a full interview.

Sections below describing Live, WebSockets, mid-call snapshots and
session resumption are superseded; see `interviewer.py` and `docs/LEARN.md`.

## 1. What we're building

SpeakWell becomes a **live mock-interview simulator**. You pick an interview,
an AI interviewer runs it out loud like a real recruiter or engineer would, and
when it's over you get a graded report with feedback pinned to the exact moment
you said something.

There is **no feedback during the interview**. A real interviewer doesn't coach
you mid-interview, so neither does this. The report comes at the end.

### Choices on the setup screen

| Choice | Options |
|---|---|
| Track | Software Engineering · AI/ML Engineering · Cybersecurity |
| Level | Intern · New grad |
| Interview | Coding (Python) · System design · Behavioral · Resume deep dive |
| Interviewer style | Warm · Neutral · Tough · Random |

### Interview lengths

Based on typical real-world rounds (45–60 min technical, ~30 min behavioral and
background calls). You see a countdown clock; you never see how many questions
are left.

| Interview | Length | Phases (approximate, hidden from you) |
|---|---|---|
| Coding | 45 min | Intro 5 · Problem + follow-ups 35 · Your questions 5 |
| System design | 45 min | Intro 5 · Requirements 10 · Design + deep dives 25 · Your questions 5 |
| Behavioral | 30 min | Intro 3 · 3–4 questions with follow-ups 22 · Your questions 5 |
| Resume deep dive | 30 min | Intro 3 · 2–3 projects, each explained then drilled 22 · Your questions 5 |

### What each track × interview means

| | Coding (Python) | System design |
|---|---|---|
| **Software Engineering** | Data structures & algorithms | Distributed systems: rate limiter, URL shortener, key-value store, chat, news feed, job queue |
| **AI/ML Engineering** | Algorithms with an ML flavor, no libraries: top-k with a heap, a k-means step, a tokenizer, sliding-window metrics | ML systems: RAG chatbot, recommender, model serving, feature store, evaluation pipeline |
| **Cybersecurity** | Python scripting: parse logs to spot brute-force logins, detect anomalies, validate inputs, hash checks | Secure design and threat modeling: secure login, secrets management, detection/logging pipeline |

Behavioral and resume deep dive are the same format across tracks, but the
questions are tailored to the track and level. Intern vs new grad changes
difficulty and expectations (e.g. how much scale and failure handling the
system design interviewer pushes on).

### Interviewer behavior (the "realism" rules)

- **The interviewer leads.** It follows a hidden plan, steers you back if you
  drift, and decides when to move on. You can't take over the interview.
- **It cuts you off when you ramble**, politely or bluntly depending on style.
- **Coding hints:** given when you're stuck, from a prepared hint ladder. Each
  hint is logged and lowers the grade a little.
- **Ends with "Do you have any questions for me?"** Your questions get graded too.
- **You can end early** and still get graded on what you covered.
- **Speaks out loud with live captions.** Chrome only. Headphones recommended so
  your mic doesn't pick up the interviewer's voice.

## 2. What goes away

Practice mode, the old mock interview, and their endpoints (`/api/prompt`,
`/api/analyze`, `/api/interview/*`) are removed, along with `prompts.py`'s
random prompts and the old four-score model. The two UI bugs found in review
(mic stuck on after switching modes, mislabeled results) disappear with them;
the new UI is built so leaving an interview always stops the mic.

The local history database (`speakwell.db`) currently has 0 sessions, so
nothing is lost when the schema changes.

## 3. Architecture walkthrough

### The pieces

```
 Browser (Chrome)                    Your server (FastAPI, 127.0.0.1)         Google
 ────────────────                    ────────────────────────────────         ──────
 Setup screen ── POST /api/interviews ──► Planner ───────────────────────────► Flash / Argon
                                          (builds hidden interview plan)
 Interview room
  mic ─ PCM audio ─┐                      Director ◄──────── WebSocket ──────► Gemini Live
  speaker ◄─ audio ┼── WebSocket ───────► (holds plan, clock, timeline,        (the voice)
  captions ◄─ text ┤   /live              phase nudges, tool calls)
  editor/notes ────┘
  recorder (your voice, in memory)

 Report screen ── POST /grade ──────────► Grader ── your audio ──────────────► Transcribe
                  (recording + code)               timeline + audio ─────────► Flash / Argon
                                          └─► SQLite: score + feedback only
```

### Step by step: one interview

1. **Setup.** You choose track, level, interview type and style, then press
   **Start interview**. You see "Starting up interview…".
2. **Seed pick (in code, instant).** `catalog.py` holds curated lists:
   coding patterns per track, system design prompts per track, behavioral
   competencies. The server picks one seed, weighted away from seeds you've had
   in your last ~10 interviews (read from the database). **This is what keeps
   interviews varied and keeps them from being AI slop:** the model elaborates
   a known-good topic instead of inventing one from nothing.
3. **Plan (Planner model, 2–40 s).** The planner turns the seed into a full
   hidden plan with a fixed JSON shape: phases with time budgets, the
   questions or problem, what each phase assesses, likely follow-ups, a grading
   rubric, and for coding a problem statement, examples, constraints, hidden
   reference solution and complexity, and a 3-step hint ladder. The server
   **validates** the plan (e.g. coding problems must have examples and hints);
   an invalid plan is retried or falls back to the next model.
4. **Live session.** The browser opens a WebSocket to *your* server, which
   opens one to Gemini Live. Your API key never reaches the browser. The server
   relays audio both ways and keeps a **timeline**: every interviewer line and
   every one of your turns, with timestamps from the interview clock.
5. **The director (server-side).** This is the part that makes the interview
   structured instead of an endless back-and-forth:
   - The Live model's instructions contain the persona, the plan, and the rules
     (you lead, don't reveal the plan or question count, no coaching, hints
     only from the ladder).
   - The Live model calls **tools** the server provides: `advance_phase`,
     `give_hint`, `end_interview`. Each call is logged in the timeline.
   - The server runs the **phase clock**. When a phase runs over, it sends the
     interviewer a private note ("wrap up requirements, move to design").
   - It watches **your turn length**. Past a threshold (~90 s behavioral, ~2
     min technical) it tells the interviewer to interject.
   - It forwards **code / notes snapshots** when you pause typing for a few
     seconds and the content changed, so the interviewer can ask "why a
     hashmap here?"
6. **Your recording.** The browser also records your mic locally (in memory)
   for grading. Live's own transcript drops filler words, so it isn't good
   enough for grading.
7. **End.** The interviewer calls `end_interview` (or you press End). The
   browser uploads your recording plus your final code or notes.
8. **Grading.**
   1. **Transcribe** your recording with `gemini-3.5-transcribe` in verbatim
      mode with word-level timestamps. It kept "Um" in testing where Live
      dropped it. It allows 30 min per request with timestamps, so longer
      recordings are split with ffmpeg and the offsets added back.
   2. **Compute in code** what code can compute exactly: filler counts and
      rate, words per minute per turn, longest pauses, hints used, time per
      phase.
   3. **Grade** with the grader model, given the merged timeline, your audio
      (for tone and engagement), the rubric, your final code or notes, and the
      computed stats.
9. **Report.** An overall score and category scores, all 0–100, plus
   **moments**: a timestamp, a short quote, what was wrong, and a better way
   to say it. Also filler words, pace, engagement (energy, interest, rapport),
   strengths, and what to work on next.
10. **Save.** Scores and feedback go into SQLite. The transcript, audio and
    code are discarded.

### Report categories (each 0–100)

| Interview | Categories |
|---|---|
| Coding | Problem understanding · Approach & problem solving · Code correctness · Code quality · Complexity analysis · Communication (hints lower the problem-solving score) |
| System design | Requirements gathering · High-level design · Deep dives & trade-offs · Scale & failure handling · Communication |
| Behavioral | Structure (STAR) · Specificity & impact · Ownership · Reflection · Communication |
| Resume deep dive | Depth of understanding · Technical accuracy · Clarity · Ownership |
| **All** | Delivery: filler words · Pace · Engagement · Your questions for them |

### Models

All model names live in settings, so they can change without code changes.
Every call has a timeout and falls through the chain on errors, timeouts, 429s
and 503s. The error you see names the actual cause (e.g. "quota exceeded"),
not "something went wrong".

| Job | Chain today (free key) | After the Pro + billing upgrade |
|---|---|---|
| Live interviewer | `gemini-3.8-live` → `gemini-3.1-flash-live-preview` | same |
| Planner + grader (text) | `gemini-4-argon` → `gemini-3.8-flash` → `gemini-3.5-flash-lite` | |
| Delivery (audio tone) | `gemini-3.5-flash-lite` → `gemini-3.8-flash` | |
| Transcription | `gemini-3.5-transcribe` | same |


Hydrogen is dropped: it returned 503 on 3 of 4 test calls, and the one success
took 198 s.

### Live API constraints we have to handle

- **Session length:** audio sessions end at 15 min without context window
  compression, and a single connection lasts about 10 min. We enable
  compression and **session resumption**, and reconnect on Google's "GoAway"
  warning so a 45-minute interview survives without you noticing.
- **Context size:** the model's input limit is 131k tokens. Code snapshots are
  sent only when changed, and compression trims old turns.
- **Interrupting you:** by default, your speech interrupts the AI, not the other
  way around. Whether the AI can talk over you mid-sentence needs a spike
  (see Risks). Fallback: it interjects at your next short pause.

### Data storage (SQLite, `speakwell.db`)

```
interviews
  id, created_at, track, level, kind, persona, seed_id,
  duration_sec, ended_early, overall_score,
  scores_json   -- category scores
  report_json   -- moments (with short quotes), strengths, improvements, delivery stats
  usage_json    -- tokens used per model, for cost tracking

resume
  id = 1, text, updated_at   -- one saved resume, "Clear resume" button
```

No transcripts, audio or code are stored. The moments in a report include short
quotes of what you said, because that's what makes the feedback exact.

### Security

- **API key:** read from the git-ignored `.env`.
- **Key never reaches the browser:** the Live connection is proxied through
  the server.
- **WebSocket origin check:** the existing cross-site guard only covers normal
  requests. The `/live` WebSocket checks the `Origin` header itself, so another
  site you have open can't hijack an interview.
- **Localhost only, no auth:** unchanged; it's for you only.
- **Bounded inputs:** caps on recording size, resume length, code/notes
  snapshot size, and interview duration.

### Endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/interviews` | Setup choices → pick seed, build plan, return interview id |
| `WS /api/interviews/{id}/live` | Audio, captions, snapshots, end signal |
| `POST /api/interviews/{id}/grade` | Recording + final code/notes → report |
| `GET /api/interviews` | History and progress (scores over time) |
| `GET/PUT/DELETE /api/resume` | Saved resume |

### Files

| File | Change |
|---|---|
| `config.py` | Model chains, budget, timeouts |
| `models.py` (new) | `call_with_fallback`: chain, timeout, retry, readable errors |
| `catalog.py` (new) | Curated seeds per track × interview type, personas |
| `planner.py` (new) | Seed + choices → validated hidden plan |
| `live.py` (new) | Gemini Live bridge + director (clock, tools, nudges, timeline, resumption) |
| `grading.py` (new) | Split audio, transcribe, compute stats, grade, validate report |
| `storage.py` | New `interviews` and `resume` tables |
| `main.py` | New endpoints, WebSocket origin check; old endpoints removed |
| `audio.py` | Keep the safe ffmpeg wrapper; add splitting into chunks |
| `gemini_client.py`, `prompts.py` | Removed (replaced by the files above) |
| `static/` | Rebuilt: setup, loading, interview room, report, history, resume |
| `static/audio-worklet.js` (new) | Mic → 16 kHz PCM capture and 24 kHz playback |
| `README.md` | Rewritten for the new app |

The Python editor is CodeMirror 6 with Python highlighting, loaded from a CDN.
Code isn't run; the interviewer and grader read it.

## 4. Build order

Each phase ends with passing tests, a short walkthrough of what was added, and
a quiz for you.

0. **Foundation.** Model fallback chain with readable errors,
   new database schema, old modes removed. **Spike:** a bare Live bridge
   through the server, to test interrupting you mid-sentence and session
   resumption before building on them.
1. **Live interview core (behavioral first).** Behavioral needs only voice, so
   it builds the shared pieces (setup, plan, director, clock, captions, End)
   without the editor.
2. **Grading and report.** Transcription, stats, grader, report screen, saving,
   history/progress charts.
3. **Coding.** Seeds, CodeMirror editor, snapshots, hint ladder and penalty.
4. **System design.** Seeds, notes box, requirements/deep-dive phases.
5. **Resume deep dive.** Resume page, saved resume, project drill-down plan.
6. **Polish.** Personas tuned, variety weighting, cost per interview shown in
   history, README.

## 5. Risks and open items

| Risk | Plan |
|---|---|
| AI talking over you mid-sentence may not be supported | Spike in phase 0; fallback is interjecting at your next pause |
| Verbatim-mode setting name for Transcribe is unconfirmed (default "smart" mode removes fillers) | Check docs and test in phase 2 |
| Planner takes 13–40 s on the free key | Loading screen; Argon after upgrade |
| Real cost per interview not measured (Live may bill accumulated context per turn) | Log token usage per interview; show it in history |
| Echo from speakers into mic | Chrome echo cancellation on; headphones recommended |
| Free-tier privacy: Google may use inputs and human reviewers may read them | Upgrade to a paid key before pasting your real resume |

## 6. Testing

- Unit tests with mocked Gemini, as today: fallback chain, plan validation,
  seed weighting, stats, report validation, storage, endpoints, WebSocket
  origin check.
- A fake Live session to test the director: phase clock, tool calls, nudges,
  snapshot forwarding, reconnect on GoAway.
- A manual checklist per interview type (run one real short interview each).
