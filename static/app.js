const recordBtn = document.getElementById("recordBtn");
const promptBtn = document.getElementById("promptBtn");
const promptInput = document.getElementById("promptInput");
const contextSelect = document.getElementById("contextSelect");
const contextDetail = document.getElementById("contextDetail");
const tipsEl = document.getElementById("tips");
const modeSwitch = document.getElementById("modeSwitch");
const modeOptions = document.querySelectorAll(".mode-option");
const promptLabel = document.getElementById("promptLabel");
const interviewCard = document.getElementById("interviewCard");
const answerCritique = document.getElementById("answerCritique");
const modelAnswer = document.getElementById("modelAnswer");
const recordingCard = document.getElementById("recordingCard");
const player = document.getElementById("player");
const paceEl = document.getElementById("pace");
const timerEl = document.getElementById("timer");
const statusEl = document.getElementById("status");
const results = document.getElementById("results");
const scoresEl = document.getElementById("scores");
const transcriptEl = document.getElementById("transcript");
const feedbackEl = document.getElementById("feedback");

const SCORE_LABELS = {
  filler_words: "Filler words",
  pace_pauses: "Pace & pauses",
  clarity_structure: "Clarity & structure",
  confidence_tone: "Confidence & tone",
};

let mediaRecorder = null;
let chunks = [];
let timerId = null;
let seconds = 0;
let recordStartMs = 0;
let durationSec = 0;
let objectUrl = null;

function setStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.classList.toggle("error", isError);
}

function fmt(t) {
  const m = Math.floor(t / 60);
  const s = String(t % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function buildContext() {
  const parts = [];
  if (contextSelect.value) parts.push(contextSelect.value);
  const detail = contextDetail.value.trim();
  if (detail) parts.push(detail);
  return parts.join(". ");
}

let mode = "practice";
const isInterview = () => mode === "interview";

function updateInterviewUi() {
  const on = isInterview();
  promptBtn.textContent = on ? "Give me an interview question" : "Give me a prompt";
  promptLabel.textContent = on ? "Interview question" : "Your speaking prompt (optional)";
  promptInput.placeholder = on
    ? "Click ‘Give me an interview question’, or type your own…"
    : "Type your own prompt to speak about, or click ‘Give me a prompt’…";
}

function setMode(next) {
  if (next === mode) return;
  mode = next;
  modeOptions.forEach((b) => {
    const active = b.dataset.mode === mode;
    b.classList.toggle("is-active", active);
    b.setAttribute("aria-selected", active ? "true" : "false");
  });
  modeSwitch.classList.toggle("interview", isInterview());
  updateInterviewUi();
}
modeOptions.forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

promptBtn.addEventListener("click", async () => {
  const on = isInterview();
  promptBtn.disabled = true;
  setStatus(on ? "Finding an interview question…" : "Finding a prompt for you…");
  try {
    const fd = new FormData();
    fd.append("context", buildContext());
    const url = on ? "/api/interview-question" : "/api/prompt";
    const r = await fetch(url, { method: "POST", body: fd });
    if (!r.ok) throw new Error();
    const data = await r.json();
    promptInput.value = on ? data.question : data.prompt;
    setStatus("");
  } catch {
    setStatus("Could not load a prompt.", true);
  } finally {
    promptBtn.disabled = false;
  }
});

recordBtn.addEventListener("click", async () => {
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    chunks = [];
    mediaRecorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    mediaRecorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      stopTimer();
      durationSec = (Date.now() - recordStartMs) / 1000;
      const blob = new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" });
      setupPlayer(blob);
      analyze(blob);
    };
    recordStartMs = Date.now();
    mediaRecorder.start();
    startTimer();
    recordBtn.textContent = "■ Stop";
    recordBtn.classList.add("recording");
    results.hidden = true;
    setStatus("Recording… click Stop when you're done.");
  } catch {
    setStatus("Microphone access was denied. Please allow it and try again.", true);
  }
});

function startTimer() {
  seconds = 0;
  timerEl.textContent = fmt(0);
  timerId = setInterval(() => { seconds += 1; timerEl.textContent = fmt(seconds); }, 1000);
}
function stopTimer() {
  clearInterval(timerId);
  recordBtn.textContent = "● Record";
  recordBtn.classList.remove("recording");
}

async function analyze(blob) {
  setStatus("Analyzing your speech…");
  recordBtn.disabled = true;
  const fd = new FormData();
  fd.append("audio", blob, "recording.webm");
  fd.append("prompt", promptInput.value.trim());
  fd.append("context", buildContext());
  if (isInterview()) fd.append("interview", "1");
  try {
    const r = await fetch("/api/analyze", { method: "POST", body: fd });
    const data = await r.json();
    if (!r.ok) { setStatus(data.error || "Analysis failed.", true); return; }
    render(data);
    setStatus("");
  } catch {
    setStatus("Something went wrong contacting the server.", true);
  } finally {
    recordBtn.disabled = false;
  }
}

function setupPlayer(blob) {
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = URL.createObjectURL(blob);
  player.src = objectUrl;
}

function paceLabel(wpm) {
  if (wpm < 110) return "Relaxed pace";
  if (wpm <= 150) return "Great conversational pace";
  if (wpm <= 170) return "A touch fast";
  return "Quite fast — try slowing down";
}

function computeWpm(transcript, seconds) {
  const words = (transcript || "").trim().split(/\s+/).filter(Boolean).length;
  if (seconds < 1 || words === 0) return null;
  return Math.round(words / (seconds / 60));
}

function renderPace(transcript) {
  const wpm = computeWpm(transcript, durationSec);
  if (wpm === null) {
    paceEl.hidden = true;
    return;
  }
  paceEl.textContent = `${wpm} words/min · ${paceLabel(wpm)}`;
  paceEl.hidden = false;
}

function colorFor(v) {
  return v >= 75 ? "var(--good)" : v >= 50 ? "var(--mid)" : "var(--bad)";
}

function render(data) {
  scoresEl.innerHTML = "";
  for (const [key, label] of Object.entries(SCORE_LABELS)) {
    const v = data.scores[key];
    const card = document.createElement("div");
    card.className = "score-card";
    card.innerHTML =
      `<div class="label">${label}</div>` +
      `<div class="value">${v}</div>` +
      `<div class="score-bar"><span style="width:${v}%;background:${colorFor(v)}"></span></div>`;
    scoresEl.appendChild(card);
  }
  if (data.answer_critique && data.model_answer) {
    answerCritique.textContent = data.answer_critique;
    modelAnswer.textContent = data.model_answer;
    interviewCard.hidden = false;
  } else {
    interviewCard.hidden = true;
  }
  transcriptEl.innerHTML = highlight(data.transcript, data.filler_words || []);
  feedbackEl.textContent = data.feedback;
  tipsEl.innerHTML = "";
  for (const tip of data.tips || []) {
    const li = document.createElement("li");
    li.textContent = tip;
    tipsEl.appendChild(li);
  }
  recordingCard.hidden = false;
  renderPace(data.transcript);
  results.hidden = false;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function highlight(transcript, fillers) {
  let html = escapeHtml(transcript);
  const uniq = [...new Set(fillers.filter(Boolean))];
  for (const f of uniq) {
    const esc = escapeHtml(f).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    html = html.replace(new RegExp(`\\b${esc}\\b`, "gi"),
      (m) => `<span class="filler">${m}</span>`);
  }
  return html;
}
