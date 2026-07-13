import { getRayfinClient, isLocalBackend } from './rayfinClient';
import type { AuthUser } from './IAuthService';

// ---------------------------------------------------------------------------
// Domain types (mirror the rayfin/data entities)
// ---------------------------------------------------------------------------
export type Mode = 'auto' | 'supervised';
export type Status = 'healthy' | 'warning' | 'critical';

export interface MachineSnapshot {
  id: string;
  machineId: string;
  lineId: string;
  product: string;
  mode: Mode;
  status: Status;
  currentDefectRate: number;
  tempC: number;
  pressureBar: number;
  tempSetpoint: number;
  pressureSetpoint: number;
  coolingTimeS: number;
  parts: number;
  defects: number;
  vibration: number;
  updatedAt: Date;
}

export interface Recommendation {
  id: string;
  machineId: string;
  observedDefectRate: number;
  recommendedTemp: number;
  recommendedPressure: number;
  expectedDefectRate: number;
  rationale: string;
  status: 'pending' | 'applied' | 'dismissed';
  createdAt: Date;
}

export interface TrendPoint {
  id: string;
  machineId: string;
  ts: Date;
  defectRate: number;
  tempSetpoint: number;
}

export interface SetpointCommand {
  id: string;
  machineId: string;
  kind: 'setpoint' | 'mode';
  tempSetpoint: number;
  pressureSetpoint: number;
  coolingTimeS: number;
  mode: Mode;
  requestedBy: string;
  status: 'requested' | 'applied' | 'error';
  note?: string;
  createdAt: Date;
  appliedAt?: Date;
}

export interface LoopEvent {
  id: string;
  machineId: string;
  ts: Date;
  kind: string;
  message: string;
}

// ---------------------------------------------------------------------------
// Local-dev in-memory store (used when no Fabric backend is configured).
// Seeded to mirror the live MfgRTI demo state so the console previews fully.
// ---------------------------------------------------------------------------
interface Store {
  snapshots: MachineSnapshot[];
  recommendations: Recommendation[];
  trend: TrendPoint[];
  commands: SetpointCommand[];
  events: LoopEvent[];
  seeded: boolean;
}

const mem: Store = {
  snapshots: [], recommendations: [], trend: [], commands: [], events: [], seeded: false,
};

function seed(): void {
  if (mem.seeded) return;
  const now = Date.now();
  mem.snapshots = [
    snap('IMM-01', 'LINE-A', 'Housing-A12', 'auto', 0.029, 221.8, 910, 221.8, 910, 12.1),
    snap('IMM-02', 'LINE-A', 'Bezel-B7', 'auto', 0.032, 225.6, 928, 225.6, 928, 11.4),
    snap('IMM-03', 'LINE-B', 'Clip-C3', 'auto', 0.05, 216.4, 903, 216.4, 903, 12.6),
    snap('IMM-04', 'LINE-B', 'Gear-D9', 'supervised', 0.14, 230.0, 882, 230.0, 882, 13.5),
  ];
  mem.recommendations = [{
    id: crypto.randomUUID(), machineId: 'IMM-04', observedDefectRate: 0.14,
    recommendedTemp: 227.1, recommendedPressure: 896, expectedDefectRate: 0.056,
    rationale: 'SPSA step -> recommend T 227.1C P 896bar (awaiting operator)',
    status: 'pending', createdAt: new Date(now),
  }];
  // Synthetic 2h convergence trend for each machine.
  for (const s of mem.snapshots) {
    const start = s.machineId === 'IMM-04' ? 0.15 : 0.12;
    const end = s.machineId === 'IMM-04' ? 0.14 : s.currentDefectRate;
    for (let i = 0; i < 40; i++) {
      const f = i / 39;
      const base = s.machineId === 'IMM-04'
        ? start + (end - start) * f
        : start * Math.exp(-3 * f) + end;
      mem.trend.push({
        id: crypto.randomUUID(), machineId: s.machineId,
        ts: new Date(now - (40 - i) * 3 * 60 * 1000),
        defectRate: Math.max(0.005, base + (Math.random() - 0.5) * 0.006),
        tempSetpoint: s.tempSetpoint,
      });
    }
  }
  mem.events = [
    evt('IMM-01', 'optimizer-applied', 'Auto loop converged to 2.9% defects'),
    evt('IMM-03', 'optimizer-applied', 'Auto loop adjusting toward optimum (5.0%)'),
    evt('IMM-04', 'recommendation', 'New recommendation pending operator approval'),
  ];
  mem.seeded = true;
}

function snap(machineId: string, lineId: string, product: string, mode: Mode,
              dr: number, tempC: number, pressureBar: number, tSp: number,
              pSp: number, cool: number): MachineSnapshot {
  return {
    id: crypto.randomUUID(), machineId, lineId, product, mode,
    status: dr > 0.08 ? 'critical' : dr > 0.045 ? 'warning' : 'healthy',
    currentDefectRate: dr, tempC, pressureBar, tempSetpoint: tSp,
    pressureSetpoint: pSp, coolingTimeS: cool,
    parts: 50, defects: Math.round(50 * dr), vibration: 0.2 + dr * 2,
    updatedAt: new Date(),
  };
}

function evt(machineId: string, kind: string, message: string): LoopEvent {
  return { id: crypto.randomUUID(), machineId, ts: new Date(), kind, message };
}

function statusOf(dr: number): Status {
  return dr > 0.08 ? 'critical' : dr > 0.045 ? 'warning' : 'healthy';
}

// ---------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------
export async function listSnapshots(): Promise<MachineSnapshot[]> {
  if (isLocalBackend()) { seed(); return sortByMachine([...mem.snapshots]); }
  const client = getRayfinClient();
  const rows = (await client.data.MachineSnapshot.select([
    'id', 'machineId', 'lineId', 'product', 'mode', 'status', 'currentDefectRate',
    'tempC', 'pressureBar', 'tempSetpoint', 'pressureSetpoint', 'coolingTimeS',
    'parts', 'defects', 'vibration', 'updatedAt',
  ]).execute()) as MachineSnapshot[];
  return sortByMachine(rows.map((r) => ({ ...r, updatedAt: new Date(r.updatedAt) })));
}

export async function listPendingRecommendations(): Promise<Recommendation[]> {
  if (isLocalBackend()) { seed(); return mem.recommendations.filter((r) => r.status === 'pending'); }
  const client = getRayfinClient();
  const rows = (await client.data.Recommendation.select([
    'id', 'machineId', 'observedDefectRate', 'recommendedTemp', 'recommendedPressure',
    'expectedDefectRate', 'rationale', 'status', 'createdAt',
  ]).where({ status: { eq: 'pending' } }).execute()) as Recommendation[];
  return rows.map((r) => ({ ...r, createdAt: new Date(r.createdAt) }));
}

export async function listTrend(): Promise<TrendPoint[]> {
  if (isLocalBackend()) { seed(); return [...mem.trend]; }
  const client = getRayfinClient();
  const rows = (await client.data.TrendPoint.select([
    'id', 'machineId', 'ts', 'defectRate', 'tempSetpoint',
  ]).orderBy({ ts: 'asc' }).execute()) as TrendPoint[];
  return rows.map((r) => ({ ...r, ts: new Date(r.ts) }));
}

export async function listRecentEvents(limit = 20): Promise<LoopEvent[]> {
  if (isLocalBackend()) { seed(); return [...mem.events].slice(-limit).reverse(); }
  const client = getRayfinClient();
  const rows = (await client.data.LoopEvent.select([
    'id', 'machineId', 'ts', 'kind', 'message',
  ]).orderBy({ ts: 'desc' }).execute()) as LoopEvent[];
  return rows.slice(0, limit).map((r) => ({ ...r, ts: new Date(r.ts) }));
}

export async function listRecentCommands(limit = 20): Promise<SetpointCommand[]> {
  if (isLocalBackend()) { seed(); return [...mem.commands].slice(-limit).reverse(); }
  const client = getRayfinClient();
  const rows = (await client.data.SetpointCommand.select([
    'id', 'machineId', 'kind', 'tempSetpoint', 'pressureSetpoint', 'coolingTimeS',
    'mode', 'requestedBy', 'status', 'note', 'createdAt', 'appliedAt',
  ]).orderBy({ createdAt: 'desc' }).execute()) as SetpointCommand[];
  return rows.slice(0, limit).map((r) => ({ ...r, createdAt: new Date(r.createdAt) }));
}

// ---------------------------------------------------------------------------
// Commands (operator actions that close the loop)
// ---------------------------------------------------------------------------
async function issueCommand(cmd: Omit<SetpointCommand, 'id' | 'status' | 'createdAt'>,
                            logMessage: string, logKind: string): Promise<SetpointCommand> {
  const record: SetpointCommand = {
    ...cmd, id: crypto.randomUUID(), status: 'requested', createdAt: new Date(),
  };

  if (isLocalBackend()) {
    seed();
    mem.commands.push(record);
    mem.events.push(evt(cmd.machineId, logKind, logMessage));
    // Optimistically reflect the command in the local snapshot for preview.
    const s = mem.snapshots.find((m) => m.machineId === cmd.machineId);
    if (s) {
      if (cmd.kind === 'mode') s.mode = cmd.mode;
      if (cmd.kind === 'setpoint') {
        s.tempSetpoint = cmd.tempSetpoint;
        s.pressureSetpoint = cmd.pressureSetpoint;
        s.coolingTimeS = cmd.coolingTimeS;
        // simulate improvement after applying a recommendation
        const rec = mem.recommendations.find((r) => r.machineId === cmd.machineId && r.status === 'pending');
        if (rec) { s.currentDefectRate = rec.expectedDefectRate; s.status = statusOf(rec.expectedDefectRate); rec.status = 'applied'; }
        s.tempC = cmd.tempSetpoint; s.pressureBar = cmd.pressureSetpoint;
      }
      s.updatedAt = new Date();
    }
    record.status = 'applied';
    record.appliedAt = new Date();
    return { ...record };
  }

  const client = getRayfinClient();
  const created = (await client.data.SetpointCommand.create({
    machineId: record.machineId, kind: record.kind, tempSetpoint: record.tempSetpoint,
    pressureSetpoint: record.pressureSetpoint, coolingTimeS: record.coolingTimeS,
    mode: record.mode, requestedBy: record.requestedBy, status: 'requested',
    note: record.note, createdAt: record.createdAt,
  })) as SetpointCommand;
  await client.data.LoopEvent.create({
    machineId: cmd.machineId, ts: new Date(), kind: logKind, message: logMessage,
  });
  return { ...created, createdAt: new Date(created.createdAt) };
}

export async function applyRecommendation(
  snapshot: MachineSnapshot, rec: Recommendation, actor: AuthUser
): Promise<SetpointCommand> {
  const cmd = await issueCommand({
    machineId: rec.machineId, kind: 'setpoint',
    tempSetpoint: rec.recommendedTemp, pressureSetpoint: rec.recommendedPressure,
    coolingTimeS: snapshot.coolingTimeS, mode: snapshot.mode, requestedBy: actor.email,
    note: `Approved optimizer recommendation (expected ${(rec.expectedDefectRate * 100).toFixed(1)}% defects)`,
  }, `${actor.name} approved recommendation -> T ${rec.recommendedTemp}C P ${rec.recommendedPressure}bar`,
     'operator-apply');
  if (!isLocalBackend()) {
    const client = getRayfinClient();
    await client.data.Recommendation.update({ id: rec.id }, { status: 'applied' });
  }
  return cmd;
}

export async function overrideSetpoint(
  snapshot: MachineSnapshot, temp: number, pressure: number, cooling: number, actor: AuthUser
): Promise<SetpointCommand> {
  return issueCommand({
    machineId: snapshot.machineId, kind: 'setpoint', tempSetpoint: temp,
    pressureSetpoint: pressure, coolingTimeS: cooling, mode: snapshot.mode,
    requestedBy: actor.email, note: 'Manual operator override',
  }, `${actor.name} set manual override T ${temp}C P ${pressure}bar`, 'operator-override');
}

export async function setMode(
  snapshot: MachineSnapshot, mode: Mode, actor: AuthUser
): Promise<SetpointCommand> {
  return issueCommand({
    machineId: snapshot.machineId, kind: 'mode', tempSetpoint: snapshot.tempSetpoint,
    pressureSetpoint: snapshot.pressureSetpoint, coolingTimeS: snapshot.coolingTimeS,
    mode, requestedBy: actor.email, note: `Switched loop to ${mode}`,
  }, `${actor.name} switched ${snapshot.machineId} to ${mode.toUpperCase()} mode`, 'mode-change');
}

function sortByMachine(rows: MachineSnapshot[]): MachineSnapshot[] {
  return rows.sort((a, b) => a.machineId.localeCompare(b.machineId));
}
