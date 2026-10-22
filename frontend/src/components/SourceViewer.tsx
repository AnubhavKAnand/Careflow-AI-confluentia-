// Shows the original input behind any fact: the report image with the exact line boxed, the PDF,
// the voice note cued to the second, and the text (original or English translation) with the span highlighted.
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Languages, Play } from "lucide-react";
import { api, type Evidence, type Source } from "../api/client";
import { fmtTime } from "./EvidenceChip";
import { Confidence, SOURCE_KIND } from "./ui";

function Highlighted({ text, ev }: { text: string; ev: Evidence | null }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    ref.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [ev?.start, ev?.end, ev?.source_id]);
  if (!ev || ev.start === null || ev.end === null || ev.end > text.length) return <>{text}</>;
  return (
    <>
      {text.slice(0, ev.start)}
      <mark ref={ref} className="evidence">
        {text.slice(ev.start, ev.end)}
      </mark>
      {text.slice(ev.end)}
    </>
  );
}

function useFileUrl(src: Source | undefined) {
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!src?.has_file) return;
    let alive = true;
    let made: string | null = null;
    setUrl(null);
    setErr(null);
    api
      .sourceFileUrl(src.id)
      .then((u) => {
        made = u;
        if (alive) setUrl(u);
      })
      .catch((e) => alive && setErr(String(e.message || e)));
    return () => {
      alive = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [src?.id, src?.has_file]);
  return { url, err };
}

export function SourceViewer({
  sources,
  selectedId,
  evidence,
  onSelectSource,
}: {
  sources: Source[];
  selectedId: number | null;
  evidence: Evidence | null;
  onSelectSource: (id: number) => void;
}) {
  const src = sources.find((s) => s.id === selectedId) ?? sources[0];
  const ev = evidence && src && evidence.source_id === src.id ? evidence : null;
  const [showTranslation, setShowTranslation] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const { url, err } = useFileUrl(src);

  useEffect(() => {
    setShowTranslation(Boolean(ev?.in_translation));
  }, [ev, src?.id]);

  useEffect(() => {
    if (ev?.locator?.start_s !== undefined && audioRef.current) audioRef.current.currentTime = ev.locator.start_s;
  }, [ev, url]);

  const isImage = src?.mime?.startsWith("image/");
  const isPdf = src?.mime === "application/pdf";
  const isAudio = src?.mime?.startsWith("audio/");
  const lowLines = useMemo(() => (src?.reading.lines ?? []).filter((l) => l.confidence < 0.6 && l.bbox), [src]);

  if (!src) return <p className="p-4 text-sm text-ink-soft">No sources.</p>;
  const r = src.reading;
  const text = showTranslation && src.translated_text ? src.translated_text : src.original_text;
  const box = ev?.locator?.bbox;

  return (
    <div className="flex h-full flex-col">
      <div className="flex gap-1 overflow-x-auto border-b border-rule px-2 pt-2" role="tablist" aria-label="Sources">
        {sources.map((s) => (
          <button
            key={s.id}
            role="tab"
            aria-selected={s.id === src.id}
            onClick={() => onSelectSource(s.id)}
            className={`whitespace-nowrap rounded-t-md border border-b-0 px-3 py-1.5 text-sm ${
              s.id === src.id ? "border-rule bg-panel font-bold text-ink" : "border-transparent text-ink-soft hover:text-ink"
            }`}
          >
            {s.id}. {SOURCE_KIND[s.kind] ?? s.kind}
            {(s.reading.quality_flags ?? []).some((f) => f.severity !== "info") && (
              <AlertTriangle className="ml-1 inline h-3.5 w-3.5 text-unclear" aria-label="has quality issues" />
            )}
          </button>
        ))}
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto bg-panel p-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-soft">
          {r.filename && <span className="font-bold text-ink">{r.filename}</span>}
          {src.language && <span>Language: {src.language}</span>}
          {r.engine && (
            <span className="inline-flex items-center gap-1.5">
              Read by {r.engine} <Confidence value={r.avg_confidence} label="Reading confidence" />
            </span>
          )}
          {r.legibility && r.legibility !== "good" && <span className="font-bold text-unclear">Legibility: {r.legibility}</span>}
        </div>

        {(r.quality_flags ?? []).filter((f) => f.severity !== "info").map((f, i) => (
          <p key={i} className={`rounded-md px-3 py-2 text-sm ${f.severity === "critical" ? "bg-p1-wash text-p1" : "bg-unclear-wash text-ink"}`}>
            {f.detail}
          </p>
        ))}

        {src.has_file && err && <p className="text-sm text-p1">Could not load the original file: {err}</p>}

        {isImage && url && (
          <div className="relative overflow-hidden rounded-md border border-rule">
            <img src={url} alt={`Original ${SOURCE_KIND[src.kind] ?? "file"}`} className="block w-full" />
            {lowLines.map((l, i) => (
              <div
                key={i}
                className="absolute border border-dashed border-unclear/70"
                style={{ left: `${l.bbox![0] / 10}%`, top: `${l.bbox![1] / 10}%`, width: `${(l.bbox![2] - l.bbox![0]) / 10}%`, height: `${(l.bbox![3] - l.bbox![1]) / 10}%` }}
                title={`Low confidence (${Math.round(l.confidence * 100)}%): ${l.text}`}
              />
            ))}
            {box && (
              <div
                className="pulse-once absolute rounded-sm border-[3px] border-p1 bg-yellow-300/25"
                style={{ left: `${box[0] / 10}%`, top: `${box[1] / 10}%`, width: `${(box[2] - box[0]) / 10}%`, height: `${(box[3] - box[1]) / 10}%` }}
                aria-label="Highlighted evidence"
              />
            )}
          </div>
        )}

        {isPdf && url && <iframe src={url} title="Original PDF" className="h-96 w-full rounded-md border border-rule" />}

        {isAudio && url && (
          <div className="space-y-2">
            <audio ref={audioRef} src={url} controls className="w-full" />
            {(r.segments ?? []).length > 0 && (
              <ol className="space-y-1 text-sm">
                {r.segments!.map((s, i) => {
                  const active = ev?.locator?.start_s !== undefined && s.start_s <= ev.locator.start_s && ev.locator.start_s < s.end_s + 0.01;
                  return (
                    <li key={i} className={`flex items-start gap-2 rounded px-2 py-1 ${active ? "bg-yellow-100" : ""}`}>
                      <button
                        className="inline-flex shrink-0 items-center gap-1 text-xs font-bold text-accent"
                        onClick={() => {
                          if (audioRef.current) {
                            audioRef.current.currentTime = s.start_s;
                            void audioRef.current.play();
                          }
                        }}
                      >
                        <Play className="h-3 w-3" aria-hidden /> {fmtTime(s.start_s)}
                      </button>
                      <span className={s.confidence < 0.6 ? "text-unclear underline decoration-dotted" : ""}>{s.text}</span>
                      <Confidence value={s.confidence} label="Transcription confidence" />
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
        )}

        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <h3 className="text-sm font-bold text-ink">{isImage || isPdf ? "Text read from the document" : isAudio ? "Full transcript" : "Text"}</h3>
            {src.translated_text && (
              <div className="inline-flex rounded-md border border-rule text-xs" role="group" aria-label="Text version">
                <button onClick={() => setShowTranslation(false)} className={`px-2 py-1 ${!showTranslation ? "bg-accent text-white" : ""}`}>
                  Original
                </button>
                <button
                  onClick={() => setShowTranslation(true)}
                  className={`inline-flex items-center gap-1 px-2 py-1 ${showTranslation ? "bg-accent text-white" : ""}`}
                >
                  <Languages className="h-3.5 w-3.5" aria-hidden /> English
                </button>
              </div>
            )}
          </div>
          {showTranslation && src.translation_confidence !== null && (
            <p className="mb-1 text-xs text-ink-soft">
              Machine translation <Confidence value={src.translation_confidence} label="Translation confidence" />. Check the original for anything important.
            </p>
          )}
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md border border-rule bg-ward/60 p-3 font-sans text-sm leading-relaxed">
            {text ? <Highlighted text={text} ev={ev && ev.in_translation === showTranslation ? ev : null} /> : <span className="text-ink-faint">No text could be read from this source.</span>}
          </pre>
        </div>
      </div>
    </div>
  );
}
