import { useMemo } from 'react';

export interface Series {
  machineId: string;
  color: string;
  points: { t: number; v: number }[];
}

interface TrendChartProps {
  series: Series[];
  height?: number;
  yLabel?: string;
  yMax?: number;
  asPercent?: boolean;
}

// Lightweight, dependency-free multi-line SVG chart used for the defect-rate
// trend. Scales x by time and y from 0..yMax.
export function TrendChart({ series, height = 220, yLabel, yMax, asPercent = true }: TrendChartProps) {
  const W = 760;
  const H = height;
  const padL = 44;
  const padB = 26;
  const padT = 12;
  const padR = 12;

  const { xMin, xMax, yTop } = useMemo(() => {
    let xmn = Infinity, xmx = -Infinity, ymx = 0;
    for (const s of series) {
      for (const p of s.points) {
        xmn = Math.min(xmn, p.t);
        xmx = Math.max(xmx, p.t);
        ymx = Math.max(ymx, p.v);
      }
    }
    if (!isFinite(xmn)) { xmn = 0; xmx = 1; }
    const top = yMax ?? Math.max(0.02, ymx * 1.15);
    return { xMin: xmn, xMax: xmx, yTop: top };
  }, [series, yMax]);

  const sx = (t: number) =>
    padL + ((t - xMin) / Math.max(1, xMax - xMin)) * (W - padL - padR);
  const sy = (v: number) =>
    padT + (1 - v / yTop) * (H - padT - padB);

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yTop);
  const fmtY = (v: number) => (asPercent ? `${(v * 100).toFixed(0)}%` : v.toFixed(2));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={yLabel ?? 'trend'}>
      {yTicks.map((v, i) => (
        <g key={i}>
          <line x1={padL} y1={sy(v)} x2={W - padR} y2={sy(v)} stroke="#e5e7eb" strokeWidth="1" />
          <text x={padL - 6} y={sy(v) + 3} textAnchor="end" fontSize="10" fill="#9ca3af">
            {fmtY(v)}
          </text>
        </g>
      ))}
      {series.map((s) => {
        if (s.points.length === 0) return null;
        const d = s.points
          .map((p, i) => `${i === 0 ? 'M' : 'L'}${sx(p.t).toFixed(1)},${sy(p.v).toFixed(1)}`)
          .join(' ');
        return (
          <path key={s.machineId} d={d} fill="none" stroke={s.color} strokeWidth="2"
                strokeLinejoin="round" strokeLinecap="round" opacity="0.9" />
        );
      })}
    </svg>
  );
}
