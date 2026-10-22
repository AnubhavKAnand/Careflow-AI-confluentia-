// Small, dependency-free line chart for percentages (0-100%, one y-axis).
// Thin 2px lines, recessive grid, legend + direct end labels (identity never by colour alone; the
// baseline series is also dashed), crosshair tooltip on hover, and a table view.
// Palette validated with the dataviz validator for light mode: #00897d (agent), #6a5fd6 (rules).
import { useId, useMemo, useRef, useState } from "react";

export interface Series {
  name: string;
  color: string;
  dashed?: boolean;
  values: (number | null)[]; // 0-1
}

export function LineChart({
  title,
  xLabels,
  xTitle,
  series,
  threshold,
  height = 220,
}: {
  title: string;
  xLabels: string[];
  xTitle: string;
  series: Series[];
  threshold?: { value: number; label: string };
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);
  const id = useId();
  const W = 640;
  const H = height;
  const pad = { l: 40, r: 96, t: 12, b: 34 };
  const iw = W - pad.l - pad.r;
  const ih = H - pad.t - pad.b;
  const n = xLabels.length;
  const x = (i: number) => pad.l + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
  const y = (v: number) => pad.t + ih - v * ih;

  const paths = useMemo(
    () =>
      series.map((s) => {
        let d = "";
        let pen = false;
        s.values.forEach((v, i) => {
          if (v === null) {
            pen = false;
            return;
          }
          d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
          pen = true;
        });
        return d;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [series, n, H],
  );

  const lastPoint = (s: Series) => {
    for (let i = s.values.length - 1; i >= 0; i--) if (s.values[i] !== null) return { i, v: s.values[i]! };
    return null;
  };
  // direct labels: nudge apart when two end labels would overlap
  const ends = series.map((s) => ({ s, p: lastPoint(s) })).filter((e) => e.p) as { s: Series; p: { i: number; v: number } }[];
  const labelY = ends.map((e) => y(e.p.v));
  for (let k = 1; k < labelY.length; k++) if (Math.abs(labelY[k] - labelY[k - 1]) < 14) labelY[k] = labelY[k - 1] + (labelY[k] >= labelY[k - 1] ? 14 : -14);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r || n === 0) return;
    const px = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(((px - pad.l) / iw) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };
  const pct = (v: number | null) => (v === null ? "no data" : `${Math.round(v * 100)}%`);

  return (
    <figure className="space-y-2">
      <figcaption className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-bold">{title}</span>
        <button type="button" onClick={() => setTable((t) => !t)} className="text-xs text-accent hover:underline">
          {table ? "Show chart" : "Show table"}
        </button>
      </figcaption>
      <ul className="flex flex-wrap gap-4 text-xs text-ink-soft" aria-label="Legend">
        {series.map((s) => (
          <li key={s.name} className="inline-flex items-center gap-1.5">
            <svg width="22" height="8" aria-hidden>
              <line x1="0" y1="4" x2="22" y2="4" stroke={s.color} strokeWidth="2" strokeDasharray={s.dashed ? "4 3" : undefined} />
            </svg>
            {s.name}
          </li>
        ))}
        {threshold && (
          <li className="inline-flex items-center gap-1.5">
            <svg width="22" height="8" aria-hidden>
              <line x1="0" y1="4" x2="22" y2="4" stroke="#7b8d8b" strokeWidth="1" strokeDasharray="2 2" />
            </svg>
            {threshold.label}
          </li>
        )}
      </ul>
      {table ? (
        <div className="max-h-64 overflow-auto rounded border border-rule">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-panel text-ink-soft">
              <tr>
                <th className="px-2 py-1 text-left font-normal">{xTitle}</th>
                {series.map((s) => (
                  <th key={s.name} className="px-2 py-1 text-right font-normal">
                    {s.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {xLabels.map((lab, i) => (
                <tr key={lab} className="border-t border-rule">
                  <td className="px-2 py-1">{lab}</td>
                  {series.map((s) => (
                    <td key={s.name} className="px-2 py-1 text-right">
                      {pct(s.values[i])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="relative">
          <svg
            ref={svgRef}
            viewBox={`0 0 ${W} ${H}`}
            className="w-full"
            role="img"
            aria-labelledby={`${id}-t`}
            onMouseMove={onMove}
            onMouseLeave={() => setHover(null)}
          >
            <title id={`${id}-t`}>{title}</title>
            {[0, 0.25, 0.5, 0.75, 1].map((t) => (
              <g key={t}>
                <line x1={pad.l} x2={pad.l + iw} y1={y(t)} y2={y(t)} stroke="#d3dcd9" strokeWidth="1" />
                <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" fontSize="11" fill="#7b8d8b">
                  {t * 100}%
                </text>
              </g>
            ))}
            {threshold && (
              <line x1={pad.l} x2={pad.l + iw} y1={y(threshold.value)} y2={y(threshold.value)} stroke="#7b8d8b" strokeWidth="1" strokeDasharray="2 2" />
            )}
            {xLabels.map((lab, i) =>
              n <= 13 || i % Math.ceil(n / 13) === 0 || i === n - 1 ? (
                <text key={lab} x={x(i)} y={H - pad.b + 16} textAnchor="middle" fontSize="11" fill="#7b8d8b">
                  {lab}
                </text>
              ) : null,
            )}
            <text x={pad.l + iw / 2} y={H - 4} textAnchor="middle" fontSize="11" fill="#4b5f5d">
              {xTitle}
            </text>
            {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + ih} stroke="#4b5f5d" strokeWidth="1" opacity="0.4" />}
            {series.map((s, k) => (
              <g key={s.name}>
                <path d={paths[k]} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dashed ? "6 4" : undefined} />
                {hover !== null && s.values[hover] !== null && (
                  <circle cx={x(hover)} cy={y(s.values[hover]!)} r="4" fill={s.color} stroke="#fff" strokeWidth="2" />
                )}
              </g>
            ))}
            {ends.map((e, k) => (
              <text key={e.s.name} x={x(e.p.i) + 8} y={labelY[k] + 4} fontSize="11" fill="#19302f">
                {e.s.name.split(" ")[0]} {Math.round(e.p.v * 100)}%
              </text>
            ))}
          </svg>
          {hover !== null && (
            <div
              className="pointer-events-none absolute top-0 rounded-md border border-rule bg-panel px-2 py-1 text-xs shadow"
              style={{ left: `${Math.min(70, (x(hover) / W) * 100)}%` }}
              role="status"
            >
              <div className="font-bold">
                {xTitle} {xLabels[hover]}
              </div>
              {series.map((s) => (
                <div key={s.name} className="flex items-center gap-1.5">
                  <span className="inline-block h-2 w-2 rounded-full" style={{ background: s.color }} aria-hidden />
                  {s.name}: {pct(s.values[hover])}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </figure>
  );
}
