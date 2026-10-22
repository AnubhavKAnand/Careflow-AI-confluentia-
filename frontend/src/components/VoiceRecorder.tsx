// Record a voice note in the browser (MediaRecorder). Produces a File that is uploaded like any other.
import { useEffect, useRef, useState } from "react";
import { Mic, Square } from "lucide-react";

export function VoiceRecorder({ onRecorded }: { onRecorded: (f: File) => void }) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const rec = useRef<MediaRecorder | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => () => {
    if (timer.current) window.clearInterval(timer.current);
    rec.current?.stream.getTracks().forEach((t) => t.stop());
  }, []);

  async function start() {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("This browser cannot record audio. Upload a recording instead.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const type = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
      const r = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
      const chunks: Blob[] = [];
      r.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      r.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: r.mimeType || "audio/webm" });
        const ext = blob.type.includes("ogg") ? "ogg" : blob.type.includes("mp4") ? "m4a" : "webm";
        onRecorded(new File([blob], `voice-note-${new Date().toISOString().slice(11, 19).replace(/:/g, "")}.${ext}`, { type: blob.type }));
      };
      r.start();
      rec.current = r;
      setSeconds(0);
      timer.current = window.setInterval(() => setSeconds((s) => s + 1), 1000);
      setRecording(true);
    } catch {
      setError("Microphone permission was denied. Allow it in the browser, or upload a recording.");
    }
  }

  function stop() {
    rec.current?.stop();
    if (timer.current) window.clearInterval(timer.current);
    setRecording(false);
  }

  return (
    <div className="flex items-center gap-3">
      {recording ? (
        <button type="button" onClick={stop} className="inline-flex items-center gap-2 rounded-md bg-p1 px-3 py-1.5 text-sm font-bold text-white">
          <Square className="h-4 w-4" aria-hidden /> Stop recording ({seconds}s)
        </button>
      ) : (
        <button type="button" onClick={start} className="inline-flex items-center gap-2 rounded-md border border-rule bg-panel px-3 py-1.5 text-sm font-bold hover:border-ink-faint">
          <Mic className="h-4 w-4 text-accent" aria-hidden /> Record voice note
        </button>
      )}
      {error && <span className="text-sm text-p1">{error}</span>}
    </div>
  );
}
