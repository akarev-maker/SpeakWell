const recordBtn = document.getElementById("recordBtn");
const recorder = document.getElementById("recorder");
const promptBar = document.getElementById("promptBar");
const interviewStart = document.getElementById("interviewStart");
const interviewSession = document.getElementById("interviewSession");
const interviewSummary = document.getElementById("interviewSummary");
const jdInput = document.getElementById("jdInput");
const startInterviewBtn = document.getElementById("startInterviewBtn");
const qProgress = document.getElementById("qProgress");
const qText = document.getElementById("qText");
const sessionNav = document.getElementById("sessionNav");
const nextQuestionBtn = document.getElementById("nextQuestionBtn");
const restartInterviewBtn = document.getElementById("restartInterviewBtn");
const summaryLevel = document.getElementById("summaryLevel");
const summaryText = document.getElementById("summaryText");
const summaryStrengths = document.getElementById("summaryStrengths");
const summaryImprovements = document.getElementById("summaryImprovements");
const promptBtn = document.getElementById("promptBtn");
const promptInput = document.getElementById("promptInput");
const contextSelect = document.getElementById("contextSelect");
const contextDetail = document.getElementById("contextDetail");
const contextBar = document.getElementById("contextBar");
const interviewContext = document.getElementById("interviewContext");
const roleSelect = document.getElementById("roleSelect");
const roleDetail = document.getElementById("roleDetail");
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
  if (isInterview()) {
    if (roleSelect.value) parts.push("Interviewing for " + roleSelect.value);
    const d = roleDetail.value.trim();
    if (d) parts.push(d);
  } else {
    if (contextSelect.value) parts.push(contextSelect.value);
    const d = contextDetail.value.trim();
    if (d) parts.push(d);
  }
  return parts.join(". ");
}

let mode = "practice";
const isInterview = () => mode === "interview";

let session = null;

function layout() {
  const interview = isInterview();
  const idle = interview && !session;
  const inQuestion = interview && session && !session.done;
  const inSummary = interview && session && session.done;

  contextBar.hidden = interview;
  promptBar.hidden = interview;
  interviewStart.hidden = !idle;
  interviewSession.hidden = !inQuestion;
  interviewSummary.hidden = !inSummary;
  recorder.hidden = interview && !inQuestion;
  if (!inQuestion) {
    results.hidden = true;
    sessionNav.hidden = true;
  }
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
  session = null;
  setStatus("");
  layout();
}
modeOptions.forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

promptBtn.addEventListener("click", async () => {
  promptBtn.disabled = true;
  setStatus("Finding a prompt for you…");
  try {
    const fd = new FormData();
    fd.append("context", buildContext());
    const r = await fetch("/api/prompt", { method: "POST", body: fd });
    if (!r.ok) throw new Error();
    const data = await r.json();
    promptInput.value = data.prompt;
    setStatus("");
  } catch {
    setStatus("Could not load a prompt.", true);
  } finally {
    promptBtn.disabled = false;
  }
});

// ----- Interview session controller -----
function fillList(ul, items) {
  ul.innerHTML = "";
  for (const it of items || []) {
    const li = document.createElement("li");
    li.textContent = it;
    ul.appendChild(li);
  }
}

function interviewRoleContext() {
  const parts = [];
  if (roleSelect.value) parts.push("Interviewing for " + roleSelect.value);
  const d = roleDetail.value.trim();
  if (d) parts.push(d);
  return parts.join(". ");
}

function showQuestion() {
  session.done = false;
  session.step = "main";
  session.currentQuestion = session.questions[session.index];
  qProgress.textContent = `Question ${session.index + 1} of ${session.questions.length}`;
  qText.textContent = session.currentQuestion;
  results.hidden = true;
  sessionNav.hidden = true;
  layout();
}

function presentFollowup(text) {
  session.step = "followup";
  session.currentQuestion = text;
  qProgress.textContent =
    `Question ${session.index + 1} of ${session.questions.length} · Follow-up`;
  qText.textContent = text;
  interviewSession.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function startInterview() {
  const jd = jdInput.value.trim();
  const role = interviewRoleContext();
  startInterviewBtn.disabled = true;
  setStatus("Preparing your interview…");
  try {
    const fd = new FormData();
    fd.append("jd", jd);
    fd.append("context", role);
    const r = await fetch("/api/interview/start", { method: "POST", body: fd });
    if (!r.ok) throw new Error();
    const data = await r.json();
    if (!data.questions || !data.questions.length) throw new Error();
    session = { questions: data.questions, index: 0, answers: [], jd, context: jd || role, done: false };
    setStatus("");
    showQuestion();
  } catch {
    setStatus("Couldn't start the interview. Try again.", true);
  } finally {
    startInterviewBtn.disabled = false;
  }
}
startInterviewBtn.addEventListener("click", startInterview);

async function afterSessionAnswer(data) {
  const transcript = data.transcript || "";
  session.answers.push({ question: session.currentQuestion, answer: transcript });
  const last = session.index === session.questions.length - 1;
  nextQuestionBtn.textContent = last ? "Finish & see summary" : "Next question →";
  sessionNav.hidden = false;

  // Only the main answer earns a follow-up (one per question, no nesting).
  if (session.step !== "main") return;
  setStatus("Thinking of a follow-up…");
  try {
    const fd = new FormData();
    fd.append("context", session.context);
    fd.append("question", session.currentQuestion);
    fd.append("answer", transcript);
    const r = await fetch("/api/interview/followup", { method: "POST", body: fd });
    const fu = await r.json();
    setStatus("");
    if (fu.followup) presentFollowup(fu.followup);
  } catch {
    setStatus("");  // no follow-up; user just clicks Next
  }
}

nextQuestionBtn.addEventListener("click", () => {
  if (!session) return;
  if (session.index < session.questions.length - 1) {
    session.index += 1;
    showQuestion();
  } else {
    finishInterview();
  }
});

async function finishInterview() {
  sessionNav.hidden = true;
  results.hidden = true;
  setStatus("Putting together your readiness summary…");
  try {
    const fd = new FormData();
    fd.append("jd", session.jd);
    fd.append("context", session.context);
    fd.append("answers", JSON.stringify(session.answers));
    const r = await fetch("/api/interview/summary", { method: "POST", body: fd });
    const sum = await r.json();
    if (!r.ok) {
      setStatus(sum.error || "Couldn't build the summary.", true);
      return;
    }
    session.done = true;
    summaryLevel.textContent = sum.level || "";
    summaryText.textContent = sum.summary || "";
    fillList(summaryStrengths, sum.strengths);
    fillList(summaryImprovements, sum.improvements);
    setStatus("");
    layout();
  } catch {
    setStatus("Couldn't build the summary.", true);
  }
}

restartInterviewBtn.addEventListener("click", () => {
  session = null;
  jdInput.value = "";
  setStatus("");
  layout();
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
  const inSession = isInterview() && session && !session.done;
  const fd = new FormData();
  fd.append("audio", blob, "recording.webm");
  fd.append("prompt", inSession ? session.currentQuestion : promptInput.value.trim());
  fd.append("context", inSession ? session.context : buildContext());
  if (isInterview()) fd.append("interview", "1");
  try {
    const r = await fetch("/api/analyze", { method: "POST", body: fd });
    const data = await r.json();
    if (!r.ok) { setStatus(data.error || "Analysis failed.", true); return; }
    render(data);
    setStatus("");
    if (inSession) afterSessionAnswer(data);
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

// Set initial screen visibility.
layout();
