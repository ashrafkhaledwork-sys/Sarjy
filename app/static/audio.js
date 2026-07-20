// Microphone capture with voice-activity detection, reply playback with an
// interrupt handle, and earcons. This is what turns push-to-talk into a
// hands-free assistant: the app hears when you stop talking.

const MIME_CANDIDATES = [
  "audio/webm;codecs=opus", // Chrome, Edge, Firefox
  "audio/webm",
  "audio/mp4",              // iOS Safari
];

// VAD tuning
const RMS_SPEECH_THRESHOLD = 0.015; // energy above this counts as speech
const SILENCE_HOLD_MS = 1200;       // pause length that ends an utterance
const NO_SPEECH_TIMEOUT_MS = 6000;  // auto-opened mic gives up politely
const MAX_UTTERANCE_MS = 30000;     // hard safety stop
const VAD_TICK_MS = 100;

export function pickMimeType() {
  if (typeof MediaRecorder === "undefined") return null;
  return MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m)) || "";
}

// onVadEvent fires at most once with: "speech-end" | "no-speech" | "max-length"
export async function startRecording({ onVadEvent } = {}) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mimeType = pickMimeType();
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  const chunks = [];
  recorder.addEventListener("dataavailable", (e) => {
    if (e.data.size > 0) chunks.push(e.data);
  });
  recorder.start();

  // --- voice-activity detection ---
  const vadCtx = new AudioContext();
  const analyser = vadCtx.createAnalyser();
  analyser.fftSize = 512;
  vadCtx.createMediaStreamSource(stream).connect(analyser);
  const samples = new Uint8Array(analyser.fftSize);

  let spoken = false;
  let silentMs = 0;
  let elapsedMs = 0;
  let vadDone = false;

  const timer = setInterval(() => {
    analyser.getByteTimeDomainData(samples);
    let sum = 0;
    for (const v of samples) {
      const d = (v - 128) / 128;
      sum += d * d;
    }
    const rms = Math.sqrt(sum / samples.length);
    elapsedMs += VAD_TICK_MS;

    if (rms > RMS_SPEECH_THRESHOLD) {
      spoken = true;
      silentMs = 0;
    } else if (spoken) {
      silentMs += VAD_TICK_MS;
    }

    let event = null;
    if (spoken && silentMs >= SILENCE_HOLD_MS) event = "speech-end";
    else if (!spoken && elapsedMs >= NO_SPEECH_TIMEOUT_MS) event = "no-speech";
    else if (elapsedMs >= MAX_UTTERANCE_MS) event = "max-length";
    if (event && !vadDone) {
      vadDone = true;
      clearInterval(timer);
      onVadEvent?.(event);
    }
  }, VAD_TICK_MS);

  const teardown = () => {
    vadDone = true;
    clearInterval(timer);
    vadCtx.close().catch(() => {});
    stream.getTracks().forEach((t) => t.stop());
  };

  return {
    stop() {
      return new Promise((resolve) => {
        recorder.addEventListener("stop", () => {
          teardown();
          const type = recorder.mimeType || "audio/webm";
          const ext = type.includes("mp4") ? "m4a" : "webm";
          resolve({ blob: new Blob(chunks, { type }), filename: `speech.${ext}` });
        });
        recorder.stop();
      });
    },
    cancel() {
      try {
        recorder.stop();
      } catch {}
      teardown();
    },
  };
}

// --- reply playback: returns a controller so the user can barge in ---
export function speak(audioUrl, fallbackText, { onStart, onDone }) {
  let finished = false;
  let player = null;
  const finish = () => {
    if (!finished) {
      finished = true;
      onDone();
    }
  };
  const estimateMs = Math.max(4000, fallbackText.split(/\s+/).length * 450 + 3000);
  setTimeout(finish, estimateMs);

  if (audioUrl) {
    player = new Audio(audioUrl);
    player.addEventListener("playing", () => onStart?.(), { once: true });
    player.addEventListener("ended", finish);
    player.addEventListener("error", () => {
      console.warn("streamed audio failed, using browser voice fallback");
      speakFallback(fallbackText, finish);
    });
    player.play().catch((err) => {
      console.warn("audio.play() rejected:", err?.name);
      speakFallback(fallbackText, finish);
    });
  } else {
    speakFallback(fallbackText, finish);
  }

  return {
    stop() {
      try {
        player?.pause();
      } catch {}
      try {
        speechSynthesis.cancel();
      } catch {}
      finish();
    },
  };
}

function speakFallback(text, onDone) {
  if (!("speechSynthesis" in window) || !text) return onDone();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.addEventListener("end", onDone);
  utterance.addEventListener("error", onDone);
  speechSynthesis.speak(utterance);
  // Some platforms lack a voice for the text's language and never fire events.
  setTimeout(onDone, Math.max(4000, text.split(/\s+/).length * 450 + 2000));
}

// --- earcons: tiny state chirps so ears know without looking ---
let earconCtx = null;
export function playEarcon(kind) {
  try {
    earconCtx = earconCtx || new AudioContext();
    const osc = earconCtx.createOscillator();
    const gain = earconCtx.createGain();
    osc.frequency.value = kind === "start" ? 880 : 587;
    gain.gain.value = 0.05;
    osc.connect(gain);
    gain.connect(earconCtx.destination);
    osc.start();
    osc.stop(earconCtx.currentTime + 0.09);
  } catch {
    /* purely cosmetic */
  }
}
