import { useCallback, useEffect, useMemo, useState } from 'react';

import { useAuth } from '@/hooks/AuthContext';
import { TrendChart, type Series } from '@/components/TrendChart';
import {
  applyRecommendation, listPendingRecommendations, listRecentEvents,
  listSnapshots, listTrend, overrideSetpoint, setMode,
  type LoopEvent, type MachineSnapshot, type Recommendation,
} from '@/services/clo';

const MACHINE_COLORS: Record<string, string> = {
  'IMM-01': '#6366f1', 'IMM-02': '#0ea5e9', 'IMM-03': '#10b981', 'IMM-04': '#f43f5e',
};

const STATUS_STYLE: Record<string, string> = {
  healthy: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  warning: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  critical: 'bg-rose-500/15 text-rose-300 ring-rose-500/30',
};

// Activity-feed badge styling per loop-event kind. `auto-optimized` events are
// emitted by the autonomous SPSA optimizer (via the bridge) and highlighted so
// operators can see the closed loop correcting machines on its own.
const EVENT_KIND: Record<string, { label: string; icon: string; cls: string }> = {
  'auto-optimized': { label: 'Auto', icon: '🤖', cls: 'bg-sky-500/15 text-sky-300 ring-sky-500/30' },
  'operator-apply': { label: 'Approved', icon: '✅', cls: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30' },
  'operator-override': { label: 'Override', icon: '✋', cls: 'bg-amber-500/15 text-amber-300 ring-amber-500/30' },
  'mode-change': { label: 'Mode', icon: '⚙️', cls: 'bg-violet-500/15 text-violet-300 ring-violet-500/30' },
};

function eventKind(kind: string): { label: string; icon: string; cls: string } {
  return EVENT_KIND[kind] ?? { label: kind, icon: '•', cls: 'bg-slate-600/20 text-slate-300 ring-slate-500/30' };
}

const POLL_MS = 5000;

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

export function ConsolePage() {
  const { user, signOut } = useAuth();
  const [snapshots, setSnapshots] = useState<MachineSnapshot[]>([]);
  const [recs, setRecs] = useState<Record<string, Recommendation>>({});
  const [trend, setTrend] = useState<Series[]>([]);
  const [events, setEvents] = useState<LoopEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [snaps, recList, trendPts, evts] = await Promise.all([
      listSnapshots(), listPendingRecommendations(), listTrend(), listRecentEvents(12),
    ]);
    setSnapshots(snaps);
    setRecs(Object.fromEntries(recList.map((r) => [r.machineId, r])));
    const byMachine = new Map<string, { t: number; v: number }[]>();
    for (const p of trendPts) {
      if (!byMachine.has(p.machineId)) byMachine.set(p.machineId, []);
      byMachine.get(p.machineId)!.push({ t: p.ts.getTime(), v: p.defectRate });
    }
    setTrend([...byMachine.entries()].map(([machineId, points]) => ({
      machineId, color: MACHINE_COLORS[machineId] ?? '#64748b',
      points: points.sort((a, b) => a.t - b.t),
    })));
    setEvents(evts);
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3500);
  };

  const doApply = async (s: MachineSnapshot, rec: Recommendation) => {
    if (!user) return;
    setBusy(s.machineId);
    try {
      await applyRecommendation(s, rec, user);
      showToast(`Recommendation applied to ${s.machineId}. New target: ${rec.recommendedTemp}°C / ${rec.recommendedPressure} bar`);
      await refresh();
    } finally { setBusy(null); }
  };

  const doToggleMode = async (s: MachineSnapshot) => {
    if (!user) return;
    setBusy(s.machineId);
    try {
      const next = s.mode === 'auto' ? 'supervised' : 'auto';
      await setMode(s, next, user);
      showToast(`${s.machineId} switched to ${next.toUpperCase()} mode`);
      await refresh();
    } finally { setBusy(null); }
  };

  const summary = useMemo(() => {
    const n = snapshots.length || 1;
    const avg = snapshots.reduce((a, s) => a + s.currentDefectRate, 0) / n;
    const worst = snapshots.reduce((a, s) => Math.max(a, s.currentDefectRate), 0);
    return {
      total: snapshots.length,
      auto: snapshots.filter((s) => s.mode === 'auto').length,
      supervised: snapshots.filter((s) => s.mode === 'supervised').length,
      avg, worst,
      critical: snapshots.filter((s) => s.status === 'critical').length,
    };
  }, [snapshots]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {toast && (
        <div className="fixed top-4 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-medium shadow-xl">
          {toast}
        </div>
      )}

      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="relative flex h-2.5 w-2.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
              </span>
              <h1 className="text-lg font-semibold tracking-tight">Closed-Loop Operations Console</h1>
            </div>
            <p className="mt-0.5 text-xs text-slate-400">
              Injection-molding quality control · Real-Time Intelligence on Microsoft Fabric
            </p>
          </div>
          <div className="flex items-center gap-4 text-xs text-slate-400">
            <span>{user?.email}</span>
            <button onClick={() => void signOut()} className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 hover:bg-slate-800">
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-6">
        {loading ? (
          <div className="py-24 text-center text-slate-500">Loading fleet telemetry…</div>
        ) : (
          <>
            {/* Fleet summary */}
            <section className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <Stat label="Machines" value={String(summary.total)} />
              <Stat label="Auto loop" value={String(summary.auto)} accent="text-indigo-300" />
              <Stat label="Supervised" value={String(summary.supervised)} accent="text-sky-300" />
              <Stat label="Avg defect" value={pct(summary.avg)} accent="text-slate-100" />
              <Stat label="Worst defect" value={pct(summary.worst)}
                    accent={summary.worst > 0.08 ? 'text-rose-300' : 'text-amber-300'} />
              <Stat label="Critical" value={String(summary.critical)}
                    accent={summary.critical ? 'text-rose-300' : 'text-emerald-300'} />
            </section>

            {/* Fleet trend */}
            <section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/50 p-5">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-200">Defect rate — last 2 hours</h2>
                <div className="flex flex-wrap gap-3 text-xs">
                  {snapshots.map((s) => (
                    <span key={s.machineId} className="flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-full" style={{ background: MACHINE_COLORS[s.machineId] }} />
                      {s.machineId}
                    </span>
                  ))}
                </div>
              </div>
              <TrendChart series={trend} yLabel="defect rate" />
            </section>

            {/* Machine cards */}
            <section className="grid gap-4 lg:grid-cols-2">
              {snapshots.map((s) => (
                <MachineCard key={s.machineId} s={s} rec={recs[s.machineId]}
                             busy={busy === s.machineId}
                             onApply={doApply} onToggleMode={doToggleMode}
                             onOverride={async (t, p, c) => {
                               if (!user) return;
                               setBusy(s.machineId);
                               try { await overrideSetpoint(s, t, p, c, user); showToast(`Manual override sent to ${s.machineId}`); await refresh(); }
                               finally { setBusy(null); }
                             }} />
              ))}
            </section>

            {/* Activity feed */}
            <section className="mt-6 rounded-xl border border-slate-800 bg-slate-900/50 p-5">
              <h2 className="mb-3 text-sm font-semibold text-slate-200">Loop activity</h2>
              <ul className="space-y-2">
                {events.length === 0 && <li className="text-xs text-slate-500">No recent activity.</li>}
                {events.map((e) => {
                  const k = eventKind(e.kind);
                  const auto = e.kind === 'auto-optimized';
                  return (
                    <li key={e.id} className={`flex items-start gap-2.5 rounded-lg px-2 py-1.5 text-sm ${auto ? 'bg-sky-500/5 ring-1 ring-sky-500/20' : ''}`}>
                      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: MACHINE_COLORS[e.machineId] ?? '#64748b' }} />
                      <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ${k.cls}`}>{k.icon} {k.label}</span>
                      <span className={auto ? 'text-sky-100' : 'text-slate-300'}>{e.message}</span>
                      <span className="ml-auto shrink-0 text-xs text-slate-500">{e.ts.toLocaleTimeString()}</span>
                    </li>
                  );
                })}
              </ul>
            </section>
          </>
        )}
      </main>
    </div>
  );
}

function Stat({ label, value, accent = 'text-slate-100' }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3">
      <div className="text-[11px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${accent}`}>{value}</div>
    </div>
  );
}

function MachineCard({ s, rec, busy, onApply, onToggleMode, onOverride }: {
  s: MachineSnapshot;
  rec?: Recommendation;
  busy: boolean;
  onApply: (s: MachineSnapshot, rec: Recommendation) => void;
  onToggleMode: (s: MachineSnapshot) => void;
  onOverride: (temp: number, pressure: number, cooling: number) => void;
}) {
  const [showOverride, setShowOverride] = useState(false);
  const [temp, setTemp] = useState(s.tempSetpoint);
  const [pressure, setPressure] = useState(s.pressureSetpoint);
  const [cooling, setCooling] = useState(s.coolingTimeS);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold">{s.machineId}</h3>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ring-1 ${STATUS_STYLE[s.status]}`}>
              {s.status}
            </span>
          </div>
          <p className="mt-0.5 text-xs text-slate-400">{s.lineId} · {s.product}</p>
        </div>
        <button onClick={() => onToggleMode(s)} disabled={busy}
                className={`rounded-md px-2.5 py-1 text-xs font-medium ring-1 disabled:opacity-50 ${
                  s.mode === 'auto'
                    ? 'bg-indigo-500/15 text-indigo-300 ring-indigo-500/30'
                    : 'bg-sky-500/15 text-sky-300 ring-sky-500/30'}`}
                title="Toggle auto / supervised">
          {s.mode === 'auto' ? '● AUTO' : '◐ SUPERVISED'}
        </button>
      </div>

      <div className="mt-4 flex items-end gap-6">
        <div>
          <div className="text-[11px] uppercase tracking-wider text-slate-500">Defect rate</div>
          <div className={`text-4xl font-bold ${s.status === 'critical' ? 'text-rose-400' : s.status === 'warning' ? 'text-amber-300' : 'text-emerald-300'}`}>
            {pct(s.currentDefectRate)}
          </div>
        </div>
        <div className="grid flex-1 grid-cols-3 gap-2 text-center">
          <Metric label="Temp" value={`${s.tempSetpoint.toFixed(0)}°C`} />
          <Metric label="Pressure" value={`${s.pressureSetpoint.toFixed(0)}`} unit="bar" />
          <Metric label="Cooling" value={`${s.coolingTimeS.toFixed(1)}s`} />
        </div>
      </div>

      {rec && (
        <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
          <div className="text-xs font-medium text-amber-200">Optimizer recommendation</div>
          <div className="mt-1 text-sm text-slate-200">
            Move to <b>{rec.recommendedTemp.toFixed(1)}°C</b> / <b>{rec.recommendedPressure.toFixed(0)} bar</b>
            <span className="text-slate-400"> — expected defect </span>
            <b className="text-emerald-300">{pct(rec.expectedDefectRate)}</b>
          </div>
          <button onClick={() => onApply(s, rec)} disabled={busy}
                  className="mt-2 rounded-md bg-amber-500 px-3 py-1.5 text-sm font-semibold text-slate-900 hover:bg-amber-400 disabled:opacity-50">
            {busy ? 'Applying…' : 'Approve & apply'}
          </button>
        </div>
      )}

      <div className="mt-4 flex items-center justify-between text-xs text-slate-400">
        <span>Vibration {s.vibration.toFixed(2)} · {s.parts} parts / {s.defects} defects</span>
        <button onClick={() => setShowOverride((v) => !v)} className="text-slate-300 underline-offset-2 hover:underline">
          {showOverride ? 'Hide override' : 'Manual override'}
        </button>
      </div>

      {showOverride && (
        <div className="mt-3 grid grid-cols-4 gap-2">
          <NumInput label="Temp °C" value={temp} onChange={setTemp} />
          <NumInput label="Press bar" value={pressure} onChange={setPressure} />
          <NumInput label="Cool s" value={cooling} onChange={setCooling} step={0.5} />
          <button onClick={() => onOverride(temp, pressure, cooling)} disabled={busy}
                  className="self-end rounded-md bg-slate-700 px-3 py-2 text-sm font-medium hover:bg-slate-600 disabled:opacity-50">
            Send
          </button>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="rounded-lg bg-slate-800/50 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="text-sm font-semibold text-slate-100">{value}{unit ? <span className="text-[10px] text-slate-400"> {unit}</span> : null}</div>
    </div>
  );
}

function NumInput({ label, value, onChange, step = 1 }: { label: string; value: number; onChange: (v: number) => void; step?: number }) {
  return (
    <label className="block">
      <span className="text-[10px] uppercase tracking-wider text-slate-500">{label}</span>
      <input type="number" step={step} value={value}
             onChange={(e) => onChange(parseFloat(e.target.value))}
             className="mt-0.5 w-full rounded-md border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none" />
    </label>
  );
}
