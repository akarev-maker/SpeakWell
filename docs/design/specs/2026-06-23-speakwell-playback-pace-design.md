# SpeakWell — Playback + Pace (WPM)

## Summary

Add two reliable "richer results" features to a single session, both
**frontend-only**: (1) play the recording back inside the results, and (2) show
the speaking pace in words-per-minute with a calm qualitative label. No backend,
database, Gemini-prompt, or Python-test changes — the transcript already comes
from the server, and the audio and timing already live in the browser.

## Goals

- Let the user hear their own recording back, with a play/scrub bar.
- Show overall pace (WPM) computed deterministically, with an encouraging label.
- Fit both into a single "Your recording" card at the top of the results,
  styled in the existing Soft Sage theme.

## Non-Goals

- No word-level timestamps, click-to-jump, or pace/pause timeline (explicitly
  deferred as too unreliable for now).
- No storing audio server-side; the clip stays in the browser for the session.
- No backend, database, or Gemini changes.

## Scope

Files touched:
- `static/index.html` — add the "Your recording" card markup at the top of the
  `#results` section (audio element + pace readout).
- `static/app.js` — keep the recorded `Blob`, expose it as an object URL on the
  audio element, measure precise duration, compute WPM, render the readout.
- `static/style.css` — style the recording card and the audio control in the
  Soft Sage palette.

No Python files change.

## Behavior / Data Flow

1. On record start, capture `recordStartMs = Date.now()`.
2. On record stop, capture `recordStopMs = Date.now()`; duration seconds =
   `(recordStopMs - recordStartMs) / 1000`. (Using wall-clock timing avoids the
   known Chrome bug where webm blobs report `Infinity` for `audio.duration`.)
3. The existing `Blob` is kept. Create `objectUrl = URL.createObjectURL(blob)`
   and set it as the `<audio>` `src`. Revoke any previous object URL first
   (recording again replaces it) to avoid leaks.
4. After analysis returns, compute WPM from the transcript and duration:
   - `words = transcript.trim().split(/\s+/).filter(Boolean).length`
   - `wpm = Math.round(words / (durationSeconds / 60))`
   - Guard: if `durationSeconds < 1` or `words === 0`, hide the pace readout.
5. Render the "Your recording" card: the audio player plus
   `"<wpm> words/min · <label>"`.

### WPM label bands

| WPM | Label |
|-----|-------|
| `< 110` | Relaxed pace |
| `110–150` | Great conversational pace |
| `150–170` | A touch fast |
| `> 170` | Quite fast — try slowing down |

The WPM computation is a small pure helper (`paceLabel(wpm)` and the
words/duration math) so the logic is simple and self-evidently correct.

## Layout

A single card at the **top of the `#results` section**, above the score cards:

```
🎧 Your recording
[ ▶  ──────●────────  0:14 ]      ← native audio controls
142 words/min · Great conversational pace
```

White rounded card, sage accents, consistent with the other result cards.
Everything below it (scores, transcript, feedback, tips) is unchanged.

## Error Handling

- If the browser produced no playable blob, the audio element is simply omitted
  (the rest of the results still render).
- If duration is too short or the transcript is empty, the pace line is hidden
  rather than showing a nonsensical number.
- Object URLs are revoked on re-record to prevent memory leaks.

## Testing

- **Python suite** (`pytest`) stays green — no backend changes (regression guard).
- **WPM logic check:** verify the words/duration math and `paceLabel` bands
  against known inputs (e.g. 142 words over 60s → 142 → "Great conversational
  pace"; 200 words over 60s → "Quite fast").
- **Manual/visual:** record a real clip; confirm the player plays it back and the
  WPM is sensible for the spoken length; confirm the card matches the Soft Sage
  styling.

## Reference

Builds on the Soft Sage redesign (`feat/calm-redesign`). The new card reuses the
existing result-card styling tokens.
