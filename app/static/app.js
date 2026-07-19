import { speak, startRecording } from "/audio.js?v=5";

// --- identity: stable user across sessions, fresh session per tab ---
const userId = localStorage.getItem("sarjy_user_id") ||
  (localStorage.setItem("sarjy_user_id", crypto.randomUUID()), localStorage.getItem("sarjy_user_id"));
const sessionId = sessionStorage.getItem("sarjy_session_id") ||
  (sessionStorage.setItem("sarjy_session_id", crypto.randomUUID()), sessionStorage.getItem("sarjy_session_id"));

const chat = document.getElementById("chat");
const form = document.getElementById("form");
const input = document.getElementById("input");
const send = document.getElementById("send");
const mic = document.getElementById("mic");
const statusDot = document.getElementById("status-dot");
const tagline = document.getElementById("tagline");

let recording = null;
let busy = false;

function setStatus(state, label) {
  statusDot.className = "dot " + state;
  tagline.textContent = label;
}

function bubble(role, textContent) {
  const div = document.createElement("div");
  div.className = "bubble " + role;
  div.textContent = textContent; // textContent, never innerHTML: LLM output is untrusted
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

function note(textContent) {
  const div = document.createElement("div");
  div.className = "note";
  div.textContent = textContent;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

async function converse(fields) {
  busy = true;
  send.disabled = true;
  mic.disabled = fields.audio === undefined ? false : true;
  setStatus("thinking", "Thinking…");
  const thinking = note("Sarjy is thinking…");

  try {
    const fd = new FormData();
    fd.append("session_id", sessionId);
    if (fields.text !== undefined) fd.append("text", fields.text);
    if (fields.audio !== undefined) fd.append("audio", fields.audio.blob, fields.audio.filename);

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
      setStatus("idle", "Tap the mic and talk — I remember you.");
      return;
    }

    if (fields.audio !== undefined) bubble("user", data.transcript);
    bubble("assistant", data.reply_text);
    if (data.memories_updated) note("💾 memory updated");
    renderWorkflow(data.workflow);
    setStatus("speaking", "Speaking…");
    speak(data.audio_b64, data.reply_text, () =>
      setStatus("idle", "Tap the mic and talk — I remember you.")
    );
  } catch (err) {
    thinking.remove();
    bubble("assistant", "Network error - is the server reachable?");
    setStatus("idle", "Tap the mic and talk — I remember you.");
  } finally {
    busy = false;
    send.disabled = false;
    mic.disabled = false;
    input.focus();
  }
}

// --- text path ---
form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || busy) return;
  input.value = "";
  bubble("user", text);
  converse({ text });
});

// --- workflow state panel: the FSM made visible ---
const wfPanel = document.getElementById("workflow-panel");
const wfStatus = document.getElementById("wf-status");
const wfDetail = document.getElementById("wf-detail");

function renderWorkflow(wf) {
  if (!wf || wf.status === "IDLE") {
    wfPanel.hidden = true;
    return;
  }
  wfPanel.hidden = false;
  wfStatus.textContent = wf.status;
  wfStatus.className = "wf-chip" +
    (wf.status === "COMPLETED" ? " done" : wf.status === "CANCELLED" ? " cancelled" : "");

  const parts = [];
  const slots = wf.slots || {};
  const labels = { cuisine: "cuisine", area: "area", party_size: "party", date: "date", time: "time" };
  for (const [k, label] of Object.entries(labels)) {
    if (slots[k]) parts.push(`${label}: ${slots[k]}`);
  }
  if (wf.selected) parts.push(`→ ${wf.selected}`);
  if (wf.missing?.length) parts.push(`missing: ${wf.missing.join(", ")}`);
  if (wf.options?.length) parts.push(`options: ${wf.options.map(o => o.name).join(" · ")}`);
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
document.getElementById("drawer-close").addEventListener("click", () => {
  drawer.hidden = true;
});

// --- voice path: tap to record, tap again to send ---
mic.addEventListener("click", async () => {
  if (busy) return;
  if (recording) {
    const rec = recording;
    recording = null;
    mic.classList.remove("recording");
    const { blob, filename } = await rec.stop();
    converse({ audio: { blob, filename } });
    return;
  }
  try {
    recording = await startRecording();
    mic.classList.add("recording");
    setStatus("listening", "Listening — tap again to send.");
  } catch (err) {
    note("Microphone unavailable (" + err.name + "). You can type instead.");
    setStatus("idle", "Mic blocked — typing works fine.");
  }
});
