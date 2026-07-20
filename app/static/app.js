import { playEarcon, speak, startRecording } from "/audio.js?v=11";

// --- identity: stable user across sessions, fresh session per tab ---
const userId = localStorage.getItem("sarjy_user_id") ||
  (localStorage.setItem("sarjy_user_id", crypto.randomUUID()), localStorage.getItem("sarjy_user_id"));
const sessionId = sessionStorage.getItem("sarjy_session_id") ||
  (sessionStorage.setItem("sarjy_session_id", crypto.randomUUID()), sessionStorage.getItem("sarjy_session_id"));

const chatScroll = document.getElementById("chat");
const chat = document.getElementById("chat-inner");
const form = document.getElementById("form");
const input = document.getElementById("input");
const send = document.getElementById("send");
const mic = document.getElementById("mic");
const statusDot = document.getElementById("status-dot");
const tagline = document.getElementById("tagline");

let recording = null;
let busy = false;
let stagedImage = null; // {blob, filename} waiting to ride on the next message
let currentSpeech = null; // controller for the reply being spoken (barge-in)
let convoMode = false; // voice conversation: mic reopens after each reply

const IDLE_TAGLINE = "Tap the orb once and just talk — I'll know when you're done.";

function setStatus(state, label) {
  statusDot.className = "dot " + state;
  tagline.textContent = label;
}

function bubble(role, textContent) {
  document.getElementById("empty-state")?.remove();
  const div = document.createElement("div");
  div.className = "bubble " + role;
  div.dir = "auto"; // RTL support: Arabic bubbles flow right-to-left
  div.textContent = textContent; // textContent, never innerHTML: LLM output is untrusted
  chat.appendChild(div);
  chatScroll.scrollTop = chatScroll.scrollHeight;
  return div;
}

function note(textContent) {
  const div = document.createElement("div");
  div.className = "note";
  div.textContent = textContent;
  chat.appendChild(div);
  chatScroll.scrollTop = chatScroll.scrollHeight;
  return div;
}

async function converse(fields) {
  busy = true;
  send.disabled = true;
  mic.disabled = fields.audio === undefined ? false : true;
  // A new turn always starts clean, even if the previous one got stuck.
  mic.classList.remove("speaking");
  setStatus("thinking", "Thinking…");
  mic.classList.add("thinking");
  const thinking = note("Sarjy is thinking…");
  const turnStart = performance.now();

  try {
    const fd = new FormData();
    fd.append("session_id", sessionId);
    if (fields.text !== undefined) fd.append("text", fields.text);
    if (fields.audio !== undefined) fd.append("audio", fields.audio.blob, fields.audio.filename);
    if (stagedImage) {
      fd.append("image", stagedImage.blob, stagedImage.filename);
      stagedImage = null;
      attach.classList.remove("staged");
    }

    const res = await fetch("/api/converse", {
      method: "POST",
      headers: { "X-User-Id": userId },
      body: fd,
    });
    const data = await res.json();
    thinking.remove();

    if (!res.ok) {
      const message = data.error?.message || "Something went wrong.";
      bubble("assistant", message);
      setStatus("idle", IDLE_TAGLINE);
      return;
    }

    if (fields.audio !== undefined) bubble("user", data.transcript);
    bubble("assistant", data.reply_text);
    if (data.memories_updated) note("💾 memory updated");
    renderWorkflow(data.workflow);
    setStatus("speaking", "Speaking…");
    mic.classList.add("speaking");
    currentSpeech = speak(data.audio_url, data.reply_text, {
      onStart: () => {
        const ttfa = ((performance.now() - turnStart) / 1000).toFixed(2);
        note(`⚡ first audio in ${ttfa}s`);
      },
      onDone: () => {
        currentSpeech = null;
        mic.classList.remove("speaking");
        setStatus("idle", IDLE_TAGLINE);
        // conversation mode: the mic reopens by itself after a voice reply
        if (convoMode && !busy && !recording) startListening();
      },
    });
  } catch (err) {
    thinking.remove();
    bubble("assistant", "Network error - is the server reachable?");
    setStatus("idle", IDLE_TAGLINE);
  } finally {
    busy = false;
    send.disabled = false;
    mic.disabled = false;
    mic.classList.remove("thinking");
    input.focus();
  }
}

// --- text path (typing exits hands-free mode) ---
form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || busy) return;
  convoMode = false;
  if (recording) cancelListening();
  currentSpeech?.stop();
  input.value = "";
  bubble("user", text);
  converse({ text });
});

// --- workflow state panel: the FSM made visible ---
const wfPanel = document.getElementById("workflow-panel");
const wfStatus = document.getElementById("wf-status");
const wfDetail = document.getElementById("wf-detail");

function renderWorkflow(wf) {
  const parts = [];
  const slots = wf?.slots || {};
  const labels = { cuisine: "cuisine", area: "area", party_size: "party", date: "date", time: "time" };
  for (const [k, label] of Object.entries(labels)) {
    if (slots[k]) parts.push(`${label}: ${slots[k]}`);
  }
  if (wf?.selected) parts.push(`→ ${wf.selected}`);
  if (wf?.missing?.length) parts.push(`missing: ${wf.missing.join(", ")}`);
  if (wf?.options?.length) parts.push(`options: ${wf.options.map(o => o.name).join(" · ")}`);

  // Show only when there is a real, explainable state - never a bare chip.
  if (!wf || wf.status === "IDLE" || wf.status === "CANCELLED" || parts.length === 0) {
    wfPanel.hidden = true;
    return;
  }
  wfPanel.hidden = false;
  wfStatus.textContent = wf.status === "COMPLETED" ? "BOOKED ✓" : "BOOKING · " + wf.status;
  wfStatus.className = "wf-chip" + (wf.status === "COMPLETED" ? " done" : "");
  wfDetail.textContent = parts.join("  ·  ");
}

// --- memory drawer ---
const drawer = document.getElementById("drawer");
const memoriesBtn = document.getElementById("memories-btn");
const memoriesList = document.getElementById("memories-list");

async function refreshMemories() {
  memoriesList.textContent = "";
  const res = await fetch("/api/memories", { headers: { "X-User-Id": userId } });
  const data = await res.json();
  document.getElementById("forget-all").hidden = !data.memories?.length;
  if (!data.memories?.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "Nothing yet — tell Sarjy something about yourself.";
    memoriesList.appendChild(li);
    return;
  }
  for (const m of data.memories) {
    const li = document.createElement("li");
    const key = document.createElement("span");
    key.className = "mem-key";
    key.textContent = m.key.replaceAll("_", " ");
    const value = document.createElement("span");
    value.className = "mem-value";
    value.textContent = m.value;
    const del = document.createElement("button");
    del.className = "mem-delete";
    del.textContent = "forget";
    del.addEventListener("click", async () => {
      await fetch("/api/memories/" + encodeURIComponent(m.key), {
        method: "DELETE",
        headers: { "X-User-Id": userId },
      });
      refreshMemories();
    });
    li.append(key, value, del);
    memoriesList.appendChild(li);
  }
}

memoriesBtn.addEventListener("click", () => {
  drawer.hidden = false;
  refreshMemories();
});

const forgetAll = document.getElementById("forget-all");
forgetAll.addEventListener("click", async () => {
  await fetch("/api/memories", { method: "DELETE", headers: { "X-User-Id": userId } });
  refreshMemories();
});
document.getElementById("drawer-close").addEventListener("click", () => {
  drawer.hidden = true;
});

// --- image attach: downscale client-side, ride on the next message ---
const attach = document.getElementById("attach");
const imageInput = document.getElementById("image-input");

attach.addEventListener("click", () => imageInput.click());
imageInput.addEventListener("change", async () => {
  const file = imageInput.files[0];
  imageInput.value = "";
  if (!file) return;
  const img = new Image();
  img.src = URL.createObjectURL(file);
  await img.decode();
  const scale = Math.min(1, 1024 / Math.max(img.width, img.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(img.width * scale);
  canvas.height = Math.round(img.height * scale);
  canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
  URL.revokeObjectURL(img.src);
  const blob = await new Promise((res) => canvas.toBlob(res, "image/jpeg", 0.8));
  stagedImage = { blob, filename: "photo.jpg" };
  attach.classList.add("staged");
  const preview = document.createElement("img");
  preview.src = URL.createObjectURL(blob);
  preview.style.cssText = "max-width:160px;border-radius:10px;display:block;margin-left:auto;margin-bottom:10px;";
  chat.appendChild(preview);
  note("Image attached — say or type what you want to know about it.");
});

// --- voice path: tap once, talk naturally; VAD sends when you pause ---
async function startListening() {
  if (busy || recording) return;
  try {
    recording = await startRecording({ onVadEvent: handleVad });
    convoMode = true;
    mic.classList.add("recording");
    playEarcon("start");
    setStatus("listening", "Listening — I'll send when you pause.");
  } catch (err) {
    convoMode = false;
    note("Microphone unavailable (" + err.name + "). You can type instead.");
    setStatus("idle", "Mic blocked — typing works fine.");
  }
}

async function stopAndSend() {
  const rec = recording;
  if (!rec) return;
  recording = null;
  mic.classList.remove("recording");
  playEarcon("send");
  const { blob, filename } = await rec.stop();
  converse({ audio: { blob, filename } });
}

function cancelListening() {
  recording?.cancel();
  recording = null;
  convoMode = false;
  mic.classList.remove("recording");
  setStatus("idle", IDLE_TAGLINE);
}

function handleVad(event) {
  if (!recording) return;
  if (event === "no-speech") {
    // an auto-opened mic that hears nothing stands down politely
    cancelListening();
    return;
  }
  stopAndSend(); // "speech-end" or "max-length"
}

mic.addEventListener("click", () => {
  if (busy) return;
  if (recording) {
    stopAndSend(); // manual send still works mid-listen
    return;
  }
  if (currentSpeech) {
    // barge-in: tapping while Sarjy speaks stops the reply and listens
    convoMode = true;
    currentSpeech.stop(); // onDone reopens the mic via conversation mode
    return;
  }
  startListening();
});

// Escape exits hands-free listening without sending
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && recording) cancelListening();
});
