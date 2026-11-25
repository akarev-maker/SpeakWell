import { EditorView, basicSetup, keymap, indentWithTab, python } from "/static/vendor/codemirror.js";

// ============================================================ helpers
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Tiny, safe markdown: escape first, then code blocks, inline code, bold, newlines.
function md(s) {
  let h = esc(s);
  h = h.replace(/```(?:\w+)?\n?([\s\S]*?)```/g, (_, code) => `<pre>${code}</pre>`);
  h = h.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  h = h.replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
  return h.replace(/\n/g, "<br>");
}
const mmss = (sec) => {
  sec = Math.max(0, Math.floor(sec));
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
};
const parseTime = (t) => {
  const m = /^(\d+):(\d{1,2})$/.exec(String(t || "").trim());
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
};
const clamp = (v) => {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? Math.max(0, Math.min(100, Math.round(n))) : null;
};
const color = (v) => (v == null ? "var(--line)" : v >= 75 ? "var(--good)" : v >= 55 ? "var(--mid)" : "var(--bad)");

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  let data = {};
  try { data = await r.json(); } catch { /* non-JSON error */ }
  if (!r.ok) throw new Error(data.error || `Request failed (${r.status}).`);
  return data;
}

const KIND_ICONS = { coding: "</>", system_design: "⬡", behavioral: "“ ”", resume: "≡" };
const COMMON_SCORES = { fillers: "Filler words", pace: "Pace", engagement: "Engagement", questions: "Your questions" };

// ============================================================ state
let meta = null;
const choice = Object.assign(
  { kind: "coding", track: "swe", level: "intern", persona: "random" },
  JSON.parse(localStorage.getItem("sw-choice") || "{}"),
);
let call = null; // the active Call, if any
let lastRun = null; // { info, recording, recOffset, audioUrl, finalWork } for grading/report

// ============================================================ routing
const VIEWS = ["home", "prep", "room", "grading", "report", "history", "resume"];
function show(view) {
  for (const v of VIEWS) $(`view-${v}`).hidden = v !== view;
  document.body.classList.toggle("in-call", view === "room");
  const route = view === "report" ? "history" : view;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === route));
  window.scrollTo({ top: 0 });
}

async function route() {
  if (call && call.active) return; // never navigate away from a live call
  const hash = location.hash.replace(/^#\/?/, "");
  const [page, arg] = hash.split("/");
  if (page === "history") return showHistory();
  if (page === "resume") return showResume();
  if (page === "report" && arg) return showSavedReport(arg);
  showHome();
}
window.addEventListener("hashchange", route);

// ============================================================ budget
async function refreshMeta() {
  meta = await api("/api/meta");
  const { month_usd: used, limit_usd: limit } = meta.budget;
  const pct = Math.min(100, (used / limit) * 100);
  $("budgetFill").style.width = `${pct}%`;
  $("budgetNum").textContent = `$${used.toFixed(2)} / $${limit.toFixed(0)}`;
  $("budget").classList.toggle("warn", pct >= 70 && pct < 100);
  $("budget").classList.toggle("over", pct >= 100);
}

// ============================================================ home / setup
function seg(el, items, key) {
  el.innerHTML = "";
  for (const it of items) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = it.label;
    b.classList.toggle("active", choice[key] === it.id);
    b.onclick = () => { choice[key] = it.id; saveChoice(); renderSetup(); };
    el.appendChild(b);
  }
}
function saveChoice() { localStorage.setItem("sw-choice", JSON.stringify(choice)); }

function renderSetup() {
  const grid = $("kindGrid");
  grid.innerHTML = "";
  for (const k of meta.kinds) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "kind" + (choice.kind === k.id ? " active" : "");
    b.innerHTML = `<span class="kind-icon">${esc(KIND_ICONS[k.id] || "•")}</span>
      <span class="kind-name">${esc(k.label)}</span>
      <span class="kind-min">${k.minutes} min</span>
      <span class="kind-blurb">${esc(k.blurb)}</span>`;
    b.onclick = () => { choice.kind = k.id; saveChoice(); renderSetup(); };
    grid.appendChild(b);
  }
  seg($("trackSeg"), meta.tracks, "track");
  seg($("levelSeg"), meta.levels, "level");
  seg($("personaSeg"), meta.personas, "persona");
  const needsResume = choice.kind === "resume" && !meta.has_resume;
  $("resumeWarning").hidden = !needsResume;
  $("startBtn").disabled = needsResume;
}

async function showHome() {
  show("home");
  $("setupError").textContent = "";
  try {
    await refreshMeta();
    renderSetup();
  } catch (e) {
    $("setupError").textContent = e.message;
  }
}

// ============================================================ prep + lobby
const PREP_STEPS = [
  "Picking a topic you haven't done recently",
  "Writing the interview plan",
  "Preparing follow-up questions",
  "Setting up the grading rubric",
  "Briefing your interviewer",
];
let prepAbort = null;

$("startBtn").onclick = async () => {
  show("prep");
  $("prepLoading").hidden = false;
  $("prepReady").hidden = true;
  $("prepError").textContent = "";
  let i = 0;
  $("prepStep").textContent = PREP_STEPS[0];
  const stepTimer = setInterval(() => {
    i = Math.min(i + 1, PREP_STEPS.length - 1);
    $("prepStep").textContent = PREP_STEPS[i];
  }, 9000);
  prepAbort = new AbortController();
  try {
    const info = await api("/api/interviews", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(choice), signal: prepAbort.signal,
    });
    clearInterval(stepTimer);
    await showLobby(info);
  } catch (e) {
    clearInterval(stepTimer);
    if (e.name === "AbortError") return;
    $("prepLoading").hidden = true;
    $("prepError").innerHTML = `${esc(e.message)}<br><br><a href="#/">← Back</a>`;
  }
};

async function showLobby(info) {
  $("prepLoading").hidden = true;
  $("prepReady").hidden = false;
  $("lobbyTitle").textContent = `${info.interviewer_name} is ready for you`;
  $("lobbyMeta").textContent =
    `${info.kind_label} · ${info.track} · ${info.level} · ${info.minutes} min · ${info.persona} style`;
  $("joinBtn").disabled = true;
  call = new Call(info);
  try {
    await call.prepareMic((level) => {
      $("micMeter").style.width = `${Math.min(100, level * 600)}%`;
    });
    $("micLabel").textContent = "Say something. The bar should move.";
    if (!("speechSynthesis" in window)) $("micLabel").textContent += " (This browser can't speak; you'll see captions only.)";
    $("joinBtn").disabled = false;
  } catch {
    $("micLabel").textContent = "Microphone access was blocked. Allow it in Chrome's address bar, then reload.";
  }
}

$("cancelPrepBtn").onclick = () => {
  if (call) call.teardown();
  call = null;
  location.hash = "#/";
  route();
};
$("joinBtn").onclick = () => call && call.join();

// ============================================================ the voice
// Chrome's built-in speech synthesis: free, local, and instant. Long utterances
// get cut off in Chrome, so text is spoken one sentence at a time.
const VOICE_PREFS = {
  warm: ["Google US English", "Samantha", "Karen"],
  neutral: ["Google UK English Male", "Daniel", "Alex"],
  tough: ["Google UK English Female", "Moira", "Fred"],
};
function pickVoice(persona) {
  const voices = speechSynthesis.getVoices().filter((v) => /^en[-_]/i.test(v.lang));
  for (const name of VOICE_PREFS[persona] || []) {
    const v = voices.find((x) => x.name === name);
    if (v) return v;
  }
  return voices.find((v) => /en[-_]US/i.test(v.lang)) || voices[0] || null;
}
if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = () => {};

function speak(text, persona, onDone) {
  speechSynthesis.cancel();
  const parts = (text.match(/[^.!?…]+[.!?…]+["')\]]*|[^.!?…]+$/g) || [text]).map((p) => p.trim()).filter(Boolean);
  const voice = pickVoice(persona);
  let left = parts.length;
  let done = false;
  const finish = () => { if (!done) { done = true; clearTimeout(guard); onDone(); } };
  if (!left) { onDone(); return; }
  // Chrome sometimes never fires "end" (or has no voices at all), which would
  // leave the call stuck on "speaking". Give up after a generous estimate.
  const words = text.split(/\s+/).length;
  const guard = setTimeout(finish, (words / 2.2 + 3) * 1000);
  for (const part of parts) {
    const u = new SpeechSynthesisUtterance(part);
    if (voice) u.voice = voice;
    u.lang = voice ? voice.lang : "en-US";
    u.rate = persona === "tough" ? 1.08 : 1.02;
    u.onend = u.onerror = () => { if (--left === 0) finish(); };
    speechSynthesis.speak(u);
  }
}

// ============================================================ the call
const isEditable = (el) => el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));

class Call {
  constructor(info) {
    this.info = info;
    this.active = false;
    this.state = "idle"; // idle | speaking | recording | thinking | ended
    this.editor = null;
    this.lastCap = null;
    this.fullChunks = [];
    this.recOffset = 0;
    this.answerLimit = 150;
    this.timeUpSent = false;
  }

  async prepareMic(onLevel) {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    this.ctx = new AudioContext();
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    this.ctx.createMediaStreamSource(this.stream).connect(this.analyser);
    this.levelBuf = new Float32Array(this.analyser.fftSize);
    this.onLevel = onLevel;
    this.ctx.resume().catch(() => {});
    const tick = () => {
      if (!this.analyser) return;
      this.analyser.getFloatTimeDomainData(this.levelBuf);
      let sum = 0;
      for (const v of this.levelBuf) sum += v * v;
      const rms = Math.sqrt(sum / this.levelBuf.length);
      if (this.onLevel) this.onLevel(rms);
      if (this.state === "recording") $("answerMeter").style.width = `${Math.min(100, rms * 600)}%`;
      this.raf = requestAnimationFrame(tick);
    };
    tick();
  }

  async join() {
    this.active = true;
    show("room");
    this.setupRoom();
    await this.ctx.resume();
    speechSynthesis.cancel();
    window.addEventListener("beforeunload", beforeUnload);
    window.addEventListener("keydown", this.onKey, true);
    try {
      const r = await api(`/api/interviews/${this.info.id}/begin`, { method: "POST" });
      this.t0 = performance.now();
      this.answerLimit = r.answer_limit_s;
      this.startFullRecording();
      this.startClock();
      $("roomStatus").textContent = "Live";
      $("liveDot").classList.add("on");
      $("captions").innerHTML = "";
      this.lastCap = null;
      this.interviewerSays(r.say);
    } catch (e) {
      this.fail(e.message);
    }
  }

  // --- room UI ---------------------------------------------------------
  setupRoom() {
    const { kind, interviewer_name: name, minutes } = this.info;
    $("roomName").textContent = name;
    $("roomStatus").textContent = "Connecting…";
    $("liveDot").classList.remove("on");
    $("captions").innerHTML = "";
    $("roomClock").innerHTML = `0:00 <span class="muted">/ ${minutes}:00</span>`;
    $("turnError").textContent = "";
    $("retryBtn").hidden = true;
    $("typeRow").hidden = true;
    $("typeToggle").textContent = "Type instead";
    $("endBtn").disabled = false;
    const hasWork = kind === "coding" || kind === "system_design";
    $("workspace").hidden = !hasWork;
    $("roomBody").classList.toggle("with-work", hasWork);
    $("editorWrap").hidden = kind !== "coding";
    $("notesWrap").hidden = kind !== "system_design";
    $("problemPanel").innerHTML = `<div class="placeholder">${
      kind === "coding" ? "The problem will appear here when your interviewer gets to it."
                        : "The design prompt will appear here when your interviewer gets to it."}</div>`;
    if (kind === "coding") this.mountEditor();
    if (kind === "system_design") $("notes").value = "";
    this.caption("system", `Connecting you with ${name}…`);
    this.setState("thinking");
  }

  mountEditor() {
    $("editor").innerHTML = "";
    this.editor = new EditorView({
      doc: "# Write your Python solution here.\n# Talk through your thinking as you go.\n",
      extensions: [basicSetup, python(), keymap.of([indentWithTab])],
      parent: $("editor"),
    });
  }
  code() { return this.editor ? this.editor.state.doc.toString() : ""; }
  work() {
    if (this.info.kind === "coding") return this.code();
    if (this.info.kind === "system_design") return $("notes").value;
    return "";
  }

  caption(who, text) {
    const box = $("captions");
    const div = document.createElement("div");
    div.className = `cap ${who}`;
    if (who === "interviewer" || who === "you") {
      const label = document.createElement("span");
      label.className = "who";
      label.textContent = who === "interviewer" ? this.info.interviewer_name : "You";
      div.appendChild(label);
    }
    const body = document.createElement("span");
    body.textContent = text;
    div.appendChild(body);
    box.appendChild(div);
    while (box.children.length > 40) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
    return body;
  }

  setState(state) {
    this.state = state;
    const name = this.info.interviewer_name;
    const orb = $("orb");
    orb.classList.toggle("speaking", state === "speaking");
    orb.classList.toggle("you", state === "recording");
    orb.classList.toggle("thinking", state === "thinking");
    $("stageLabel").textContent = {
      idle: "Your turn", speaking: `${name} is speaking`, recording: "Recording your answer",
      thinking: `${name} is thinking`, ended: "Interview over",
    }[state];
    const btn = $("answerBtn");
    btn.disabled = state === "thinking" || state === "ended";
    btn.classList.toggle("recording", state === "recording");
    $("answerLabel").textContent = state === "recording" ? "Done" : "Start answer";
    $("answerHint").textContent = state === "recording"
      ? "Space or ⌘↵ when you're done. Pause as long as you like."
      : state === "speaking" ? "You can start answering anytime; it'll stop talking."
      : "Space or ⌘↵ to start and stop";
    if (state !== "recording") $("answerMeter").style.width = "0%";
    $("typeSend").disabled = state === "thinking" || state === "ended" || state === "recording";
  }

  startClock() {
    const total = this.info.minutes * 60;
    this.clock = setInterval(() => {
      const t = this.elapsed();
      const el = $("roomClock");
      el.innerHTML = `${mmss(t)} <span class="muted">/ ${this.info.minutes}:00</span>`;
      el.classList.toggle("late", t > total - 300 && t <= total);
      el.classList.toggle("over", t > total);
      if (this.state === "recording") this.recordingTick();
      // If time runs out while nobody is talking, the interviewer wraps up.
      if (t > total + 45 && this.state === "idle" && !this.timeUpSent) {
        this.timeUpSent = true;
        this.sendTurn({ event: "time_up" });
      }
    }, 250);
  }
  elapsed() { return this.t0 ? (performance.now() - this.t0) / 1000 : 0; }

  startFullRecording() {
    // A local copy of the whole session, only for the report's player. It's
    // never uploaded: each answer is sent separately when you finish it.
    try {
      this.full = new MediaRecorder(this.stream, { mimeType: "audio/webm;codecs=opus", audioBitsPerSecond: 24000 });
      this.full.ondataavailable = (e) => { if (e.data.size) this.fullChunks.push(e.data); };
      this.full.start(10000);
      this.recOffset = this.elapsed();
    } catch { this.full = null; }
  }

  // --- interviewer -----------------------------------------------------------
  interviewerSays(text, then) {
    this.caption("interviewer", text);
    this.setState("speaking");
    speak(text, this.info.persona_id, () => {
      if (this.state === "speaking") this.setState("idle");
      if (then) then();
    });
  }

  // --- your answer -------------------------------------------------------------
  onKey = (e) => {
    if (!this.active) return;
    const modEnter = (e.metaKey || e.ctrlKey) && e.key === "Enter";
    const space = e.code === "Space" && !isEditable(e.target) && !e.repeat;
    if (!modEnter && !space) return;
    e.preventDefault();
    e.stopPropagation();
    this.toggleAnswer();
  };

  toggleAnswer() {
    if (this.state === "recording") this.stopAnswer(false);
    else if (this.state === "idle" || this.state === "speaking") this.startAnswer();
  }

  startAnswer() {
    speechSynthesis.cancel(); // talking over the interviewer stops it, like a real call
    $("turnError").textContent = "";
    $("retryBtn").hidden = true;
    this.chunks = [];
    this.answerStart = this.elapsed();
    this.rec = new MediaRecorder(this.stream, { mimeType: "audio/webm;codecs=opus", audioBitsPerSecond: 32000 });
    this.rec.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
    this.rec.start();
    this.setState("recording");
  }

  recordingTick() {
    const used = this.elapsed() - this.answerStart;
    const left = this.answerLimit - used;
    $("answerLabel").textContent = `Done · ${mmss(used)}`;
    if (left <= 15) $("answerHint").textContent = `Wrap up: ${Math.max(0, Math.ceil(left))} s left in this answer`;
    if (left <= 0) this.stopAnswer(true); // the interviewer cuts in
  }

  stopAnswer(autoStopped) {
    const duration = this.elapsed() - this.answerStart;
    const startedAt = this.answerStart;
    this.setState("thinking");
    this.rec.onstop = () => {
      const blob = new Blob(this.chunks, { type: this.rec.mimeType || "audio/webm" });
      this.sendTurn({ blob, startedAt, duration, autoStopped });
    };
    this.rec.stop();
  }

  sendTyped() {
    const text = $("typeInput").value.trim();
    if (!text || !(this.state === "idle" || this.state === "speaking")) return;
    speechSynthesis.cancel();
    $("typeInput").value = "";
    this.setState("thinking");
    this.sendTurn({ text, startedAt: this.elapsed(), duration: 0 });
  }

  async sendTurn({ blob, text, startedAt = 0, duration = 0, autoStopped = false, event = "" }) {
    this.setState("thinking");
    const fd = new FormData();
    if (blob) fd.append("answer", blob, "answer.webm");
    if (text) fd.append("text", text);
    fd.append("started_at", String(startedAt));
    fd.append("duration", String(duration));
    fd.append("auto_stopped", autoStopped ? "true" : "false");
    fd.append("work", this.work());
    if (event) fd.append("event", event);
    const mine = blob || text ? this.caption("you", text || "…") : null;
    try {
      const r = await api(`/api/interviews/${this.info.id}/turn`, { method: "POST", body: fd });
      this.handleReply(r, mine);
    } catch (e) {
      if (mine && blob && /didn't/.test(e.message)) mine.parentElement.remove();
      this.turnFailed(e.message);
    }
  }

  handleReply(r, mine) {
    if (!this.active) return;
    if (r.say == null) {
      if (mine) mine.parentElement.remove();
      $("turnError").textContent = r.message || "I didn't catch that.";
      this.setState("idle");
      return;
    }
    if (mine && r.heard) mine.textContent = r.heard;
    if (r.answer_limit_s) this.answerLimit = r.answer_limit_s;
    if (r.reveal) this.reveal(r.reveal);
    this.interviewerSays(r.say, r.ended ? () => this.finish() : null);
  }

  turnFailed(message) {
    $("turnError").textContent = message;
    // Your answer is already saved on the server if it got that far; Retry
    // just asks for the reply again without re-sending audio.
    $("retryBtn").hidden = !/Retry/.test(message);
    this.setState("idle");
  }

  async retry() {
    $("retryBtn").hidden = true;
    $("turnError").textContent = "";
    this.setState("thinking");
    try {
      const r = await api(`/api/interviews/${this.info.id}/retry`, { method: "POST" });
      this.handleReply(r, null);
    } catch (e) {
      this.turnFailed(`${e.message} Retry`);
    }
  }

  reveal(p) {
    if (p.type === "prompt") {
      $("problemPanel").innerHTML = `<div class="sub">Design prompt</div><p>${md(p.text)}</p>`;
      return;
    }
    const ex = (p.examples || []).map((e, i) =>
      `<div class="ex"><b>Example ${i + 1}</b>\nInput: ${esc(e.input)}\nOutput: ${esc(e.output)}${
        e.explanation ? `\n${esc(e.explanation)}` : ""}</div>`).join("");
    const cons = (p.constraints || []).map((c) => `<li>${md(c)}</li>`).join("");
    $("problemPanel").innerHTML = `<h3>${esc(p.title)}</h3><div>${md(p.statement)}</div>${ex}
      ${cons ? `<div class="sub">Constraints</div><ul>${cons}</ul>` : ""}`;
    if (this.editor && p.signature && !/\bdef\s/.test(this.code())) {
      const doc = `${p.signature.trim()}\n    pass\n`;
      this.editor.dispatch({ changes: { from: 0, to: this.editor.state.doc.length, insert: doc } });
    }
  }

  // --- ending ------------------------------------------------------------
  async endNow() {
    if (!this.t0) { this.teardown(); location.hash = "#/"; route(); return; }
    const extra = this.state === "recording" ? " The answer you're recording now won't be sent." : "";
    if (!confirm(`End the interview now? You'll still be graded on what you covered.${extra}`)) return;
    if (this.state === "recording") {
      this.rec.onstop = null;
      this.rec.stop();
    }
    const fd = new FormData();
    fd.append("work", this.work());
    try { await api(`/api/interviews/${this.info.id}/end`, { method: "POST", body: fd }); } catch { /* graded anyway */ }
    this.finish();
  }

  async finish() {
    if (this.finished) return;
    this.finished = true;
    this.setState("ended");
    clearInterval(this.clock);
    const finalWork = this.work();
    const recording = await this.stopFullRecording();
    this.teardown();
    lastRun = {
      info: this.info, recOffset: this.recOffset, finalWork,
      audioUrl: recording ? URL.createObjectURL(recording) : null,
    };
    startGrading();
  }

  stopFullRecording() {
    return new Promise((resolve) => {
      if (!this.full || this.full.state === "inactive") {
        resolve(this.fullChunks.length ? new Blob(this.fullChunks, { type: "audio/webm" }) : null);
        return;
      }
      this.full.onstop = () => resolve(new Blob(this.fullChunks, { type: "audio/webm" }));
      this.full.stop();
    });
  }

  fail(message) {
    this.teardown();
    show("prep");
    $("prepLoading").hidden = true;
    $("prepReady").hidden = true;
    $("prepError").innerHTML = `${esc(message)}<br><br><a href="#/">← Back</a>`;
  }

  teardown() {
    this.active = false;
    speechSynthesis.cancel();
    window.removeEventListener("beforeunload", beforeUnload);
    window.removeEventListener("keydown", this.onKey, true);
    clearInterval(this.clock);
    cancelAnimationFrame(this.raf);
    this.analyser = null;
    try { if (this.rec && this.rec.state !== "inactive") this.rec.stop(); } catch { /* stopped */ }
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    if (this.ctx) this.ctx.close().catch(() => {});
  }
}

function beforeUnload(e) { e.preventDefault(); e.returnValue = ""; }
$("endBtn").onclick = () => call && call.endNow();
$("answerBtn").onclick = () => call && call.toggleAnswer();
$("retryBtn").onclick = () => call && call.retry();
$("typeToggle").onclick = () => {
  const row = $("typeRow");
  row.hidden = !row.hidden;
  $("typeToggle").textContent = row.hidden ? "Type instead" : "Hide typing";
  if (!row.hidden) $("typeInput").focus();
};
$("typeSend").onclick = () => call && call.sendTyped();
$("typeInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.metaKey && !e.ctrlKey) { e.preventDefault(); if (call) call.sendTyped(); }
});

// ============================================================ grading
const STAGE_ORDER = ["delivery", "grading"];
function markStage(stage) {
  const idx = STAGE_ORDER.indexOf(stage === "starting" ? "delivery" : stage);
  document.querySelectorAll("#gradeSteps li").forEach((li, i) => {
    li.classList.toggle("done", stage === "done" || i < idx);
    li.classList.toggle("active", stage !== "done" && i === idx);
  });
}

async function startGrading() {
  show("grading");
  $("gradeError").textContent = "";
  $("gradeRetryBtn").hidden = true;
  markStage("delivery");
  const fd = new FormData();
  fd.append("final_work", lastRun.finalWork || "");
  try {
    await api(`/api/interviews/${lastRun.info.id}/grade`, { method: "POST", body: fd });
    pollGrade();
  } catch (e) {
    gradeFailed(e.message);
  }
}

async function pollGrade() {
  try {
    const st = await api(`/api/interviews/${lastRun.info.id}/grade`);
    markStage(st.stage);
    if (st.report) {
      call = null;
      refreshMeta().catch(() => {});
      history.replaceState(null, "", `#/report/${lastRun.info.id}`);
      renderReport(st.report, lastRun);
      return;
    }
    if (st.error) return gradeFailed(st.error);
    setTimeout(pollGrade, 1500);
  } catch (e) {
    gradeFailed(e.message);
  }
}

function gradeFailed(message) {
  $("gradeError").textContent = message;
  $("gradeRetryBtn").hidden = false;
  document.querySelectorAll("#gradeSteps li").forEach((li) => li.classList.remove("active"));
}
$("gradeRetryBtn").onclick = () => startGrading();

// ============================================================ report
function ring(score) {
  const v = clamp(score) ?? 0;
  const r = 60, c = 2 * Math.PI * r;
  return `<div class="ring"><svg width="140" height="140">
    <circle cx="70" cy="70" r="${r}" fill="none" stroke="var(--line)" stroke-width="10"/>
    <circle cx="70" cy="70" r="${r}" fill="none" stroke="${color(v)}" stroke-width="10" stroke-linecap="round"
      stroke-dasharray="${(c * v) / 100} ${c}"/></svg>
    <div class="ring-num"><b>${v}</b><span>out of 100</span></div></div>`;
}

const list = (items) => `<ul class="list">${(items || []).map((i) => `<li>${md(i)}</li>`).join("")}</ul>`;

function statBox(label, val, sub) {
  return `<div class="stat"><div class="stat-label">${esc(label)}</div>
    <div class="stat-val" style="color:${typeof val === "number" ? color(val) : "inherit"}">${val ?? "–"}</div>
    <div class="stat-sub">${esc(sub || "")}</div></div>`;
}

function referenceHtml(rep) {
  const ref = rep.reference || {};
  if (rep.kind === "coding" && ref.reference_solution) {
    return `<p><b>${esc(ref.title)}</b> · time ${esc(ref.time_complexity)} · space ${esc(ref.space_complexity)}</p>
      <pre>${esc(ref.reference_solution)}</pre>
      <p><b>The hints you could have gotten</b></p>${list(ref.hints)}
      <p><b>Follow-up variants</b></p>${list(ref.follow_up_variants)}`;
  }
  if (rep.kind === "system_design" && ref.prompt) {
    // Plain markdown: list() escapes each item, so HTML built here would show as literal tags.
    const facts = (ref.hidden_facts || []).map((f) => `**${f.topic}:** ${f.answer}`);
    return `<p>${md(ref.prompt)}</p><p><b>Facts you could have asked for</b></p>${list(facts)}
      <p><b>A strong design covers</b></p>${list(ref.must_cover)}
      <p><b>Deep-dive topics</b></p>${list(ref.deep_dive_topics)}
      <p><b>Common pitfalls</b></p>${list(ref.pitfalls)}`;
  }
  if (rep.kind === "behavioral" && ref.questions) {
    return ref.questions.map((q) => `<p><b>${esc(q.competency)}:</b> ${esc(q.question)}<br>
      <span class="muted">Strong answers: ${esc(q.strong_answer_signals)}</span></p>`).join("");
  }
  if (ref.projects) {
    return ref.projects.map((p) => `<p><b>${esc(p.name)}</b></p>${list([p.opening_question, ...p.drill_questions])}`).join("");
  }
  return "";
}

function renderReport(rep, run = {}) {
  show("report");
  const d = rep.delivery || {};
  const q = rep.questions_for_them || {};
  const chips = [
    `${mmss(rep.duration_sec)} of ${rep.planned_minutes}:00`,
    `${esc(rep.interviewer_name)} · ${esc(rep.persona)}`,
    rep.kind === "coding" ? `${rep.hints_used} hint${rep.hints_used === 1 ? "" : "s"}` : null,
  ].filter(Boolean).map((c) => `<span class="chip">${c}</span>`).join("")
    + (rep.ended_early ? `<span class="chip warn">Ended early</span>` : "");

  const cats = (rep.categories || []).map((c) => {
    const v = clamp(c.score);
    return `<div><div class="cat-top"><span class="cat-name">${esc(c.label)}</span>
      <span class="cat-score" style="color:${color(v)}">${v ?? "–"}</span></div>
      <div class="bar"><span style="width:${v ?? 0}%;background:${color(v)}"></span></div>
      <p class="cat-reason">${esc(c.reason)}</p></div>`;
  }).join("");

  const fillerChips = Object.entries(d.filler_counts || {}).sort((a, b) => b[1] - a[1])
    .map(([w, n]) => `<span class="filler-chip">“${esc(w)}” × ${n}</span>`).join("");
  const obs = (d.observations || []).map((o) => (o.time ? `**${o.time}** ${o.note}` : o.note));

  const canSeek = !!run.audioUrl;
  const offset = run.recOffset || 0;
  const moments = (rep.moments || []).map((m) => `
    <li class="moment ${m.type === "strength" ? "strength" : ""}">
      <button class="m-time ${canSeek ? "seek" : ""}" data-t="${esc(m.time)}" type="button">${esc(m.time)}</button>
      <div><div class="m-type">${esc(m.type)}</div>
        <blockquote class="m-quote">“${esc(m.quote)}”</blockquote>
        <p class="m-issue">${md(m.issue)}</p>
        <p class="m-better"><b>${m.type === "strength" ? "Keep it up:" : "Try instead:"}</b> ${md(m.better)}</p></div>
    </li>`).join("");

  const cost = rep.cost ? `Estimated cost $${rep.cost.total_usd.toFixed(2)}` : "";
  const ref = referenceHtml(rep);

  $("view-report").innerHTML = `
    <div class="report-hero">${ring(rep.overall_score)}
      <div><div class="muted small">${esc(rep.title)}</div>
        <h1>Your interview report</h1>
        <p class="verdict">${esc(rep.verdict)}</p><div class="chips">${chips}</div>
        ${(rep.notes || []).length ? `<div class="notes-box">${rep.notes.map(esc).join("<br>")}</div>` : ""}
      </div></div>

    ${canSeek ? `<div class="card"><h2>Your recording</h2>
      <p class="card-sub">Your microphone for the whole interview, kept only in this browser tab. Click a timestamp below to jump to it.</p>
      <div class="player-row"><audio id="repAudio" controls src="${run.audioUrl}"></audio></div></div>` : ""}

    <div class="card"><h2>Scores</h2><div class="cats">${cats}</div></div>

    <div class="card"><h2>How you sounded</h2>
      <div class="stats">
        ${statBox("Filler words", clamp(d.filler_score), d.filler_rate_per_min != null ? `${d.filler_rate_per_min} per minute` : "")}
        ${statBox("Pace", d.pace_wpm != null ? `${d.pace_wpm}` : null, d.pace_wpm != null ? "words/min · 120–160 is comfortable" : "")}
        ${statBox("Engagement", clamp(d.engagement_score), "interest, energy, rapport")}
        ${statBox("Confidence", clamp(d.confidence_score), "steadiness, conviction")}
      </div>
      ${fillerChips ? `<div class="fillers">${fillerChips}</div>` : ""}
      <div class="prose">
        ${d.engagement_feedback ? `<p>${md(d.engagement_feedback)}</p>` : ""}
        ${d.energy ? `<p><b>Energy:</b> ${esc(d.energy)}</p>` : ""}
        ${d.tone ? `<p><b>Tone:</b> ${esc(d.tone)}</p>` : ""}
        ${obs.length ? list(obs) : ""}
      </div></div>

    <div class="card"><h2>Moment by moment</h2>
      <p class="card-sub">Exactly where things went well or wrong, with what to say instead.</p>
      <ul class="moments">${moments || `<li class="muted">No specific moments were returned.</li>`}</ul></div>

    <div class="two">
      <div class="card"><h2>Strengths</h2>${list(rep.strengths)}</div>
      <div class="card"><h2>Work on next</h2>${list(rep.improvements)}</div>
    </div>

    <div class="card"><h2>Your questions for them <span class="muted small">${clamp(q.score) ?? "–"}/100</span></h2>
      <div class="prose"><p>${md(q.feedback || "")}</p></div></div>

    ${rep.work_review ? `<div class="card"><h2>${rep.kind === "coding" ? "Code review" : "Design review"}</h2>
      <div class="prose"><p>${md(rep.work_review)}</p></div></div>` : ""}

    ${ref ? `<div class="card"><details class="ref"><summary>What the interviewer was looking for</summary>
      <div class="prose">${ref}</div></details></div>` : ""}

    <div class="report-foot"><span>${cost}</span>
      <button class="btn primary" id="againBtn">Start another interview</button></div>`;

  $("againBtn").onclick = () => { location.hash = "#/"; route(); };
  if (canSeek) {
    const audio = $("repAudio");
    document.querySelectorAll(".m-time.seek").forEach((b) => {
      b.onclick = () => {
        const t = parseTime(b.dataset.t);
        if (t == null) return;
        audio.currentTime = Math.max(0, t - offset - 2);
        audio.play();
      };
    });
  }
}

async function showSavedReport(id) {
  try {
    const item = await api(`/api/history/${encodeURIComponent(id)}`);
    renderReport(item.report, lastRun && lastRun.info.id === id ? lastRun : {});
  } catch (e) {
    show("report");
    $("view-report").innerHTML = `<p class="error-text">${esc(e.message)}</p><a href="#/history">← History</a>`;
  }
}

// ============================================================ history
let historyTab = "all";

function lineChart(points) {
  const w = 900, h = 200, px = 30, py = 16;
  if (!points.length) return "";
  const x = (i) => (points.length === 1 ? w / 2 : px + (i * (w - px * 2)) / (points.length - 1));
  const y = (v) => py + ((100 - v) * (h - py * 2)) / 100;
  const grid = [25, 50, 75, 100].map((g) =>
    `<line x1="${px}" x2="${w - px}" y1="${y(g)}" y2="${y(g)}" stroke="var(--line)"/>
     <text x="0" y="${y(g) + 4}" font-size="11" fill="var(--muted)">${g}</text>`).join("");
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const dots = points.map((p, i) =>
    `<circle cx="${x(i)}" cy="${y(p.v)}" r="4.5" fill="${color(p.v)}"><title>${esc(p.label)}: ${p.v}</title></circle>`).join("");
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${grid}
    <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linejoin="round"/>${dots}</svg>`;
}

function trendCards(items, keys) {
  const chrono = items.slice().reverse();
  return Object.entries(keys).map(([key, label]) => {
    const vals = chrono.map((it) => clamp(it.scores[key])).filter((v) => v != null);
    if (!vals.length) return "";
    const last = vals[vals.length - 1];
    const prev = vals.slice(0, -1);
    const base = prev.length ? Math.round(prev.reduce((a, b) => a + b, 0) / prev.length) : null;
    const delta = base == null ? null : last - base;
    const cls = delta == null || delta === 0 ? "flat" : delta > 0 ? "up" : "down";
    const txt = delta == null ? "first one" : `${delta > 0 ? "▲" : delta < 0 ? "▼" : "–"} ${Math.abs(delta)} vs avg`;
    return `<div class="trend"><div class="trend-name">${esc(label)}</div>
      <div class="trend-row"><span class="trend-val" style="color:${color(last)}">${last}</span>
      <span class="trend-delta ${cls}">${txt}</span></div></div>`;
  }).join("");
}

async function showHistory() {
  show("history");
  const view = $("view-history");
  view.innerHTML = `<div class="page-head"><h1>History</h1></div><p class="muted">Loading…</p>`;
  let items;
  try {
    if (!meta) await refreshMeta();
    items = (await api("/api/history")).interviews;
  } catch (e) {
    view.innerHTML = `<p class="error-text">${esc(e.message)}</p>`;
    return;
  }
  const kinds = meta.kinds;
  const label = (id) => (kinds.find((k) => k.id === id) || {}).label || id;
  const shown = historyTab === "all" ? items : items.filter((i) => i.kind === historyTab);
  const tabs = [{ id: "all", label: "All" }, ...kinds].map((k) =>
    `<button class="${historyTab === k.id ? "active" : ""}" data-tab="${k.id}">${esc(k.label)}</button>`).join("");
  const points = shown.slice().reverse().filter((i) => i.overall_score != null)
    .map((i) => ({ v: i.overall_score, label: `${label(i.kind)} · ${new Date(i.created_at).toLocaleDateString()}` }));
  const keys = historyTab === "all" ? COMMON_SCORES
    : { ...Object.fromEntries((meta.rubrics[historyTab] || []).map((r) => [r.id, r.label])), ...COMMON_SCORES };

  const rows = shown.map((i) => {
    const d = new Date(i.created_at);
    const v = clamp(i.overall_score);
    return `<li data-id="${esc(i.id)}">
      <div class="hist-score" style="color:${color(v)};background:var(--panel-2)">${v ?? "–"}</div>
      <div><div class="hist-title">${esc(i.title)}</div>
        <div class="hist-sub">${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          · ${mmss(i.duration_sec)}${i.ended_early ? " · ended early" : ""} · $${(i.cost_usd || 0).toFixed(2)}</div></div>
      <span class="muted small">${esc((meta.personas.find((p) => p.id === i.persona) || {}).label || i.persona)}</span>
      <button class="hist-del" data-del="${esc(i.id)}" title="Delete">✕</button></li>`;
  }).join("");

  view.innerHTML = `<div class="page-head"><h1>History</h1>
      <p class="lede">Your scores over time. Only scores and feedback are saved, never recordings or transcripts.</p></div>
    <div class="seg tabs">${tabs}</div>
    ${shown.length ? `<div class="chart">${lineChart(points)}
        <div class="chart-legend"><span>Overall score per interview, oldest → newest</span></div></div>
      <div class="trend-grid">${trendCards(shown, keys)}</div>
      <ul class="hist">${rows}</ul>`
    : `<div class="empty">No interviews here yet. <a href="#/">Start one →</a></div>`}`;

  view.querySelectorAll("[data-tab]").forEach((b) => {
    b.onclick = () => { historyTab = b.dataset.tab; showHistory(); };
  });
  view.querySelectorAll(".hist li").forEach((li) => {
    li.onclick = (e) => {
      if (e.target.dataset.del) return;
      location.hash = `#/report/${li.dataset.id}`;
    };
  });
  view.querySelectorAll("[data-del]").forEach((b) => {
    b.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm("Delete this interview from your history?")) return;
      await api(`/api/history/${encodeURIComponent(b.dataset.del)}`, { method: "DELETE" });
      showHistory();
    };
  });
}

// ============================================================ resume
async function showResume() {
  show("resume");
  $("resumeStatus").textContent = "";
  try {
    const r = await api("/api/resume");
    $("resumeText").value = r.text || "";
    $("resumeStatus").textContent = r.updated_at ? `Saved ${new Date(r.updated_at).toLocaleString()}` : "Not saved yet";
  } catch (e) {
    $("resumeStatus").textContent = e.message;
  }
}
$("resumeSave").onclick = async () => {
  try {
    const r = await api("/api/resume", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: $("resumeText").value }),
    });
    $("resumeStatus").textContent = `Saved ${new Date(r.updated_at).toLocaleString()}`;
    if (meta) meta.has_resume = true;
  } catch (e) {
    $("resumeStatus").textContent = e.message;
  }
};
$("resumeClear").onclick = async () => {
  if (!confirm("Clear your saved resume?")) return;
  await api("/api/resume", { method: "DELETE" });
  $("resumeText").value = "";
  $("resumeStatus").textContent = "Cleared";
  if (meta) meta.has_resume = false;
};

// ============================================================ boot
route();
