// Microphone capture (MediaRecorder) and reply playback.

const MIME_CANDIDATES = [
  "audio/webm;codecs=opus", // Chrome, Edge, Firefox
  "audio/webm",
  "audio/mp4",              // iOS Safari
];

export function pickMimeType() {
  if (typeof MediaRecorder === "undefined") return null;
  return MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m)) || "";
}

export async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mimeType = pickMimeType();
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  const chunks = [];
  recorder.addEventListener("dataavailable", (e) => {
    if (e.data.size > 0) chunks.push(e.data);
  });
  recorder.start();

  return {
    stop() {
      return new Promise((resolve) => {
        recorder.addEventListener("stop", () => {
          stream.getTracks().forEach((t) => t.stop());
          const type = recorder.mimeType || "audio/webm";
          const ext = type.includes("mp4") ? "m4a" : "webm";
          resolve({ blob: new Blob(chunks, { type }), filename: `speech.${ext}` });
        });
        recorder.stop();
      });
    },
    cancel() {
      recorder.stop();
      stream.getTracks().forEach((t) => t.stop());
    },
  };
}

// Speak a reply: prefer server MP3; fall back to browser speechSynthesis.
export function speak(audioB64, fallbackText, onDone) {
  if (audioB64) {
    const player = new Audio("data:audio/mpeg;base64," + audioB64);
    player.addEventListener("ended", onDone);
    player.play().catch(() => speakFallback(fallbackText, onDone));
    return;
  }
  speakFallback(fallbackText, onDone);
}

function speakFallback(text, onDone) {
  if (!("speechSynthesis" in window) || !text) return onDone();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.addEventListener("end", onDone);
  utterance.addEventListener("error", onDone);
  speechSynthesis.speak(utterance);
}
