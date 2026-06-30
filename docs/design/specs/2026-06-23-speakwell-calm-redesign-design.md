# SpeakWell — Calm & Focused Visual Redesign

## Summary

Restyle the existing SpeakWell single-page app into a calm, focused, "Soft Sage"
aesthetic: a light sage-green background, white rounded cards, gentle muted
accent colors, serif headings, and generous whitespace. This is a **frontend-only
visual redesign** — no backend, API, or behavioral changes. The page structure
and all functionality (context, prompt, record, scores, transcript, feedback,
tips) stay exactly as they are; only the look and feel change.

## Goals

- Replace the current dark theme with the approved Soft Sage light theme.
- Use serif headings (Georgia) paired with a system sans body.
- Add the tagline "Speak. Reflect. Improve." (italic serif).
- Make the experience feel calm, distraction-free, and product-grade.

## Non-Goals

- No changes to backend, endpoints, Gemini prompt, scoring, or data shapes.
- No new features (history, playback, accounts, etc.).
- No framework — stays vanilla HTML/CSS/JS.
- No changes to the Python test suite (no JS logic changes that need new tests).

## Scope

Files touched:
- `static/style.css` — full restyle (the bulk of the work).
- `static/index.html` — tagline text change; mark up the wordmark/tagline so
  headings render in serif. No structural/element-id changes.
- `static/app.js` — only if needed for the record-button state label/class
  (it already toggles a `.recording` class and swaps "● Record" / "■ Stop").

## Design Tokens

Defined as CSS custom properties on `:root`:

| Token | Value | Use |
|-------|-------|-----|
| `--bg` | `#eef2ea` | page background (soft sage) |
| `--panel` | `#ffffff` | cards, inputs |
| `--text` | `#2f3a31` | primary text |
| `--muted` | `#7e8a7c` | labels, secondary text |
| `--accent` | `#6f9e7b` | sage accent (record button, focus, bars-good) |
| `--accent-dark` | `#5e8b6a` | hover/active accent |
| `--border` | `#d8e3d6` | card/input borders |
| `--good` | `#6f9e7b` | score ≥ 75 (sage) |
| `--mid` | `#d8a657` | score 50–74 (warm amber) |
| `--bad` | `#cf7a6b` | score < 50 (soft terracotta) |
| `--filler-bg` | `#dcebdc` | filler highlight background |
| `--filler-text` | `#3f6b4a` | filler highlight text |
| `--radius` | `16px` | card radius (`14px` for inputs) |

Typography:
- Headings / wordmark / score numbers: `Georgia, 'Times New Roman', serif`.
- Tagline: serif, italic.
- Body / labels / buttons / inputs: `system-ui, -apple-system, sans-serif`.

## Component Styling

- **Layout:** centered single column, `max-width: 620px`, generous vertical
  rhythm and padding. Calm, lots of whitespace.
- **Header:** serif "SpeakWell" wordmark (~30px); italic serif tagline
  "Speak. Reflect. Improve." in muted color beneath it.
- **Context select + prompt/detail inputs:** white, `14px` radius, `--border`
  border, sage focus ring (`--accent`). Muted placeholder text.
- **Record button:** ~104px sage circle, white label, soft sage drop shadow
  (`0 14px 32px rgba(111,158,123,.42)`); on `.recording` it becomes soft
  terracotta (`--bad`) with "■ Stop". Timer below in muted tabular numerals.
- **Score cards:** 2×2 grid (1 column under ~520px), white rounded cards,
  muted label, large **serif** number, thin rounded progress bar filled to the
  score width and colored by threshold (`--good`/`--mid`/`--bad`).
- **Transcript:** white rounded card; filler words highlighted with
  `--filler-bg` / `--filler-text` (soft sage chip).
- **Feedback:** white rounded card, comfortable line-height.
- **Tips:** white rounded card, bulleted list with sage `::marker`.
- **Status / errors:** muted for info; a calm muted-red for errors (not harsh).
- **Section headings** ("Transcript", "Coaching feedback", "How to improve"):
  serif, ~16px.

## Data Flow / Behavior

Unchanged. The DOM element IDs consumed by `app.js`
(`promptInput`, `contextSelect`, `contextDetail`, `recordBtn`, `timer`,
`status`, `results`, `scores`, `transcript`, `feedback`, `tips`) remain the
same so no JS rewiring is needed.

## Error Handling

No new error paths. The existing inline status/error messaging is restyled to
the calm palette (muted red for errors).

## Testing

- Python suite (`pytest`) must remain green — no backend changes, so the
  existing 29 tests are the regression guard.
- Visual verification: run the server, load the page, confirm the record view
  and a real results view match the approved mockup (palette, serif headings,
  tagline, rounded cards, threshold bar colors, filler highlight). Check the
  responsive single-column layout under ~520px.

## Reference

Approved mockup: `.superpowers/brainstorm/24600-1782265355/content/full-layout.html`
(Soft Sage palette + serif headings + "Speak. Reflect. Improve." tagline).
