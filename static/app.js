const recordBtn = document.getElementById("recordBtn");
const promptBtn = document.getElementById("promptBtn");
const promptText = document.getElementById("promptText");
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

function setStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.classList.toggle("error", isError);
}

function fmt(t) {
  const m = Math.floor(t / 60);
  const s = String(t % 60).padStart(2, "0");
  return `${m}:${s}`;
}

promptBtn.addEventListener("click", async () => {
  try {
    const r = await fetch("/api/prompt");
    const data = await r.json();
    promptText.textContent = data.prompt;
    promptText.hidden = false;
  } catch {
    setStatus("Could not load a prompt.", true);
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
      const blob = new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" });
      analyze(blob);
    };
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
  transcriptEl.innerHTML = highlight(data.transcript, data.filler_words || []);
  feedbackEl.textContent = data.feedback;
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
