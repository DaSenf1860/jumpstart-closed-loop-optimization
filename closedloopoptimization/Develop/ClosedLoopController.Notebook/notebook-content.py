# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {}
# META }

# MARKDOWN ********************

# # ClosedLoopController — digital twin + SPSA optimizer
# 
# One closed-loop pass: read current setpoints, emit telemetry, run the
# SPSA optimizer, and write new setpoints (auto) or a recommendation
# (supervised) back to the MfgRTI Eventhouse. **Schedule this notebook
# every ~10 minutes** to keep the loop running.

# CELL ********************

# ===== model.py — digital-twin physics + SPSA optimizer =====
"""
model.py — Digital-twin physics + closed-loop optimizer for the injection-molding
demo. Pure, deterministic-with-seed logic (no I/O) so it can be unit-tested.

The "plant": each machine has a hidden true optimum operating point (barrel
temperature, injection pressure, cooling time) that slowly DRIFTS over time.
Defect rate rises quadratically with the distance of the actual process values
from that optimum. The optimizer never sees the optimum — it only sees defect
rate, and must steer the setpoints toward it. Because the optimum drifts, the
loop never "finishes" — ideal for a live closed-loop demo.

Optimizer: SPSA (Simultaneous Perturbation Stochastic Approximation) in a
normalized parameter space. Each optimization step applies a small simultaneous
+/- dither to temperature and pressure, measures the resulting defect rate at
both perturbed points (real, visible exploration in the telemetry stream),
estimates the gradient, and takes a downhill step.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime

# --- Normalization: optimize temperature & pressure in dimensionless z-space ---
TEMP_CENTER, TEMP_SCALE = 220.0, 8.0        # z_temp  = (T - 220) / 8
PRESS_CENTER, PRESS_SCALE = 900.0, 40.0     # z_press = (P - 900) / 40
COOL_CENTER, COOL_SCALE = 12.0, 4.0

# Safe operating envelope (hard clamps on commanded setpoints)
TEMP_MIN, TEMP_MAX = 205.0, 235.0
PRESS_MIN, PRESS_MAX = 840.0, 960.0
COOL_MIN, COOL_MAX = 10.0, 16.0

# Defect-rate response surface (in z-space)
DEFECT_FLOOR = 0.010     # ~1% intrinsic defects at the optimum
DEFECT_GAIN = 0.060      # curvature: defect rate per unit squared distance
DEFECT_NOISE = 0.0035    # measurement noise (std)

# SPSA hyper-parameters (tuned for ~15-25 iters to converge; drift keeps it busy)
SPSA_C = 0.35            # perturbation size in z-space
SPSA_A = 1.8             # step gain
SPSA_MOMENTUM = 0.35

# Drift of the hidden optimum (slow) — this is what makes the loop perpetual
DRIFT_SIN_AMPL_T = 0.55  # z-units
DRIFT_SIN_AMPL_P = 0.45
DRIFT_PERIOD_MIN = 90.0  # minutes per drift cycle
DRIFT_WALK = 0.010       # tiny random walk per optimizer step

PARTS_PER_WINDOW = 50    # parts produced per telemetry window


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def t_to_z(t: float) -> float:
    return (t - TEMP_CENTER) / TEMP_SCALE


def z_to_t(z: float) -> float:
    return TEMP_CENTER + z * TEMP_SCALE


def p_to_z(p: float) -> float:
    return (p - PRESS_CENTER) / PRESS_SCALE


def z_to_p(z: float) -> float:
    return PRESS_CENTER + z * PRESS_SCALE


@dataclass
class MachineState:
    machine_id: str
    line_id: str
    product: str
    temp_sp: float
    press_sp: float
    cool_sp: float
    mode: str = "auto"                # 'auto' (loop applies) or 'supervised'
    opt_temp_z0: float = 0.0          # hidden optimum base (z-space)
    opt_press_z0: float = 0.0
    grad_temp_ema: float = 0.0        # optimizer memory
    grad_press_ema: float = 0.0
    walk_temp: float = 0.0
    walk_press: float = 0.0
    iters: int = 0
    rng_seed: int = 0
    _rng: random.Random = field(default=None, repr=False, compare=False)

    def rng(self) -> random.Random:
        if self._rng is None:
            self._rng = random.Random(self.rng_seed)
        return self._rng


def optimum_z(m: MachineState, minutes: float) -> tuple[float, float]:
    """Hidden optimum in z-space at a given elapsed time (drifting)."""
    phase = 2 * math.pi * (minutes / DRIFT_PERIOD_MIN)
    ot = m.opt_temp_z0 + DRIFT_SIN_AMPL_T * math.sin(phase) + m.walk_temp
    op = m.opt_press_z0 + DRIFT_SIN_AMPL_P * math.sin(phase + 1.1) + m.walk_press
    return ot, op


def _defect_rate_at(m: MachineState, temp: float, press: float, cool: float,
                    minutes: float, add_noise: bool) -> float:
    """Ground-truth defect rate for given ACTUAL process values (the plant)."""
    ot, op = optimum_z(m, minutes)
    dz_t = t_to_z(temp) - ot
    dz_p = p_to_z(press) - op
    dz_c = (cool - COOL_CENTER) / COOL_SCALE
    quad = dz_t * dz_t + dz_p * dz_p + 0.5 * dz_c * dz_c
    dr = DEFECT_FLOOR + DEFECT_GAIN * quad
    if add_noise:
        dr += m.rng().gauss(0.0, DEFECT_NOISE)
    return clamp(dr, 0.001, 0.65)


@dataclass
class Telemetry:
    timestamp: datetime
    machine_id: str
    line_id: str
    product: str
    temp_c: float
    pressure_bar: float
    cooling_time_s: float
    vibration: float
    cycle_time_s: float
    parts_produced: int
    defects: int
    defect_rate: float
    temp_setpoint: float
    press_setpoint: float
    mode: str


def sample_telemetry(m: MachineState, ts: datetime, minutes: float,
                     temp_cmd: float | None = None,
                     press_cmd: float | None = None) -> Telemetry:
    """One telemetry window. Actual process values track the commanded setpoints
    with small noise. temp_cmd/press_cmd override the stored setpoints (used
    during optimizer exploration)."""
    rng = m.rng()
    tsp = m.temp_sp if temp_cmd is None else temp_cmd
    psp = m.press_sp if press_cmd is None else press_cmd
    actual_temp = tsp + rng.gauss(0.0, 0.4)
    actual_press = psp + rng.gauss(0.0, 2.0)
    actual_cool = m.cool_sp + rng.gauss(0.0, 0.15)

    dr = _defect_rate_at(m, actual_temp, actual_press, actual_cool, minutes, True)
    parts = PARTS_PER_WINDOW
    defects = sum(1 for _ in range(parts) if rng.random() < dr)

    ot, op = optimum_z(m, minutes)
    quad = (t_to_z(actual_temp) - ot) ** 2 + (p_to_z(actual_press) - op) ** 2
    vibration = clamp(0.20 + 0.14 * quad + (actual_press - PRESS_CENTER) / 4000.0
                      + rng.gauss(0, 0.01), 0.05, 3.0)
    cycle_time = actual_cool + 3.0 + rng.gauss(0, 0.1)

    return Telemetry(
        timestamp=ts, machine_id=m.machine_id, line_id=m.line_id, product=m.product,
        temp_c=round(actual_temp, 2), pressure_bar=round(actual_press, 1),
        cooling_time_s=round(actual_cool, 2), vibration=round(vibration, 3),
        cycle_time_s=round(cycle_time, 2), parts_produced=parts, defects=defects,
        defect_rate=round(defects / parts, 4),
        temp_setpoint=round(tsp, 2), press_setpoint=round(psp, 1), mode=m.mode,
    )


@dataclass
class OptimizerDecision:
    observed_defect_rate: float
    recommended_temp: float
    recommended_press: float
    expected_defect_rate: float
    applied: bool
    rationale: str


def optimize_step(m: MachineState, minutes: float, measure):
    """One SPSA optimization step. `measure(temp_cmd, press_cmd) -> (defect_rate,
    telemetry)` runs the plant at a perturbed operating point (real, visible
    exploration). In 'auto' mode the recommendation is applied; in 'supervised'
    mode the setpoint is left unchanged for an operator to approve."""
    rng = m.rng()
    m.iters += 1
    zt, zp = t_to_z(m.temp_sp), p_to_z(m.press_sp)

    d_t = 1.0 if rng.random() < 0.5 else -1.0
    d_p = 1.0 if rng.random() < 0.5 else -1.0

    tp_plus, pp_plus = z_to_t(zt + SPSA_C * d_t), z_to_p(zp + SPSA_C * d_p)
    tp_minus, pp_minus = z_to_t(zt - SPSA_C * d_t), z_to_p(zp - SPSA_C * d_p)

    dr_plus, tel_plus = measure(tp_plus, pp_plus)
    dr_minus, tel_minus = measure(tp_minus, pp_minus)

    diff = (dr_plus - dr_minus) / (2.0 * SPSA_C)
    g_t, g_p = diff / d_t, diff / d_p
    m.grad_temp_ema = SPSA_MOMENTUM * m.grad_temp_ema + (1 - SPSA_MOMENTUM) * g_t
    m.grad_press_ema = SPSA_MOMENTUM * m.grad_press_ema + (1 - SPSA_MOMENTUM) * g_p

    new_temp = clamp(z_to_t(zt - SPSA_A * m.grad_temp_ema), TEMP_MIN, TEMP_MAX)
    new_press = clamp(z_to_p(zp - SPSA_A * m.grad_press_ema), PRESS_MIN, PRESS_MAX)

    observed = round((dr_plus + dr_minus) / 2.0, 4)
    expected = round(_defect_rate_at(m, new_temp, new_press, m.cool_sp, minutes, False), 4)

    m.walk_temp += rng.gauss(0, DRIFT_WALK)
    m.walk_press += rng.gauss(0, DRIFT_WALK)

    applied = m.mode == "auto"
    if applied:
        m.temp_sp, m.press_sp = new_temp, new_press
        rationale = (f"SPSA dr+={dr_plus:.3f} dr-={dr_minus:.3f} -> "
                     f"T {new_temp:.1f}C P {new_press:.0f}bar (auto-applied)")
    else:
        rationale = (f"SPSA dr+={dr_plus:.3f} dr-={dr_minus:.3f} -> recommend "
                     f"T {new_temp:.1f}C P {new_press:.0f}bar (awaiting operator)")

    return (OptimizerDecision(observed, round(new_temp, 2), round(new_press, 1),
                              expected, applied, rationale),
            [tel_plus, tel_minus])


def default_fleet() -> list[MachineState]:
    """The four demo machines with deliberately off-optimum starting setpoints."""
    return [
        MachineState("IMM-01", "LINE-A", "Housing-A12", 214.0, 860.0, 13.0,
                     mode="auto", opt_temp_z0=t_to_z(221.0), opt_press_z0=p_to_z(902.0), rng_seed=101),
        MachineState("IMM-02", "LINE-A", "Bezel-B7", 230.0, 940.0, 11.0,
                     mode="auto", opt_temp_z0=t_to_z(223.0), opt_press_z0=p_to_z(912.0), rng_seed=202),
        MachineState("IMM-03", "LINE-B", "Clip-C3", 208.0, 880.0, 14.0,
                     mode="auto", opt_temp_z0=t_to_z(217.0), opt_press_z0=p_to_z(898.0), rng_seed=303),
        MachineState("IMM-04", "LINE-B", "Gear-D9", 230.0, 882.0, 13.5,
                     mode="supervised", opt_temp_z0=t_to_z(219.0), opt_press_z0=p_to_z(905.0), rng_seed=404),
    ]

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# ===== kql_rest.py — dependency-free KQL I/O over REST =====
"""
kql_rest.py — dependency-free KQL I/O using only `requests` (available in Fabric
by default). Exposes the same interface as kql_io.KqlIO so loop.py works
unchanged, but needs no azure-kusto-data / %pip. Used by the Fabric notebook.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

import requests



def _dt(v: datetime) -> str:
    return f"datetime({v.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z)"


def _s(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


class RestKqlIO:
    def __init__(self, query_uri: str, database: str,
                 token_provider: Callable[[], str]):
        self.query_uri = query_uri.rstrip("/")
        self.database = database
        self.token_provider = token_provider

    def _post(self, endpoint: str, csl: str) -> dict:
        headers = {"Authorization": f"Bearer {self.token_provider()}",
                   "Content-Type": "application/json"}
        body = {"db": self.database, "csl": csl}
        r = requests.post(f"{self.query_uri}/v1/rest/{endpoint}", headers=headers,
                          json=body, timeout=60)
        r.raise_for_status()
        return r.json()

    def latest_setpoints(self) -> dict[str, dict]:
        q = ("Setpoints | summarize arg_max(Timestamp, *) by MachineId "
             "| project MachineId, TempSetpoint, PressureSetpoint, CoolingTimeS, Mode")
        data = self._post("query", q)
        table = data["Tables"][0]
        cols = [c["ColumnName"] for c in table["Columns"]]
        out: dict[str, dict] = {}
        for row in table["Rows"]:
            rec = dict(zip(cols, row))
            out[rec["MachineId"]] = {
                "temp": float(rec["TempSetpoint"]), "press": float(rec["PressureSetpoint"]),
                "cool": float(rec["CoolingTimeS"]), "mode": rec["Mode"],
            }
        return out

    def count_telemetry(self) -> int:
        """Total telemetry rows — used to decide whether to seed a backfill."""
        data = self._post("query", "MachineTelemetry | count")
        try:
            return int(data["Tables"][0]["Rows"][0][0])
        except (KeyError, IndexError, ValueError):
            return 0

    def append_telemetry(self, rows: list[Telemetry]) -> None:
        if not rows:
            return
        vals = ",\n".join(
            f"{_dt(t.timestamp)},{_s(t.machine_id)},{_s(t.line_id)},{_s(t.product)},"
            f"{t.temp_c},{t.pressure_bar},{t.cooling_time_s},{t.vibration},{t.cycle_time_s},"
            f"{int(t.parts_produced)},{int(t.defects)},{t.defect_rate},"
            f"{t.temp_setpoint},{t.press_setpoint},{_s(t.mode)}"
            for t in rows)
        cmd = (".set-or-append MachineTelemetry <| datatable("
               "Timestamp:datetime, MachineId:string, LineId:string, Product:string, "
               "TempC:real, PressureBar:real, CoolingTimeS:real, Vibration:real, CycleTimeS:real, "
               "PartsProduced:long, Defects:long, DefectRate:real, TempSetpoint:real, "
               "PressureSetpoint:real, Mode:string)[" + vals + "]")
        self._post("mgmt", cmd)

    def append_setpoint(self, ts: datetime, m: MachineState, source: str, note: str) -> None:
        row = (f"{_dt(ts)},{_s(m.machine_id)},{m.temp_sp},{m.press_sp},{m.cool_sp},"
               f"{_s(source)},{_s(m.mode)},{_s(note)}")
        cmd = (".set-or-append Setpoints <| datatable(Timestamp:datetime, MachineId:string, "
               "TempSetpoint:real, PressureSetpoint:real, CoolingTimeS:real, Source:string, "
               "Mode:string, Note:string)[" + row + "]")
        self._post("mgmt", cmd)

    def append_optimization(self, ts: datetime, m: MachineState, d: OptimizerDecision) -> None:
        action = "applied" if d.applied else "recommended"
        row = (f"{_dt(ts)},{_s(m.machine_id)},{d.observed_defect_rate},{m.temp_sp},{m.press_sp},"
               f"{d.recommended_temp},{d.recommended_press},{d.expected_defect_rate},"
               f"{_s(action)},{_s(m.mode)},{_s(d.rationale)}")
        cmd = (".set-or-append OptimizationEvents <| datatable(Timestamp:datetime, MachineId:string, "
               "ObservedDefectRate:real, ObservedTemp:real, ObservedPressure:real, "
               "RecommendedTemp:real, RecommendedPressure:real, ExpectedDefectRate:real, "
               "Action:string, Mode:string, Rationale:string)[" + row + "]")
        self._post("mgmt", cmd)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# ===== loop.py — orchestration (backfill + live_tick) =====
"""
loop.py — orchestration shared by the local backfill and the Fabric notebook.

One "closed loop": read current setpoints -> run the plant (emit telemetry) ->
optimizer estimates the defect-rate gradient and writes new setpoints
(auto) or a recommendation (supervised) -> repeat.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta


EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def minutes_since_epoch(ts: datetime) -> float:
    return (ts - EPOCH).total_seconds() / 60.0


def build_states(io: KqlIO) -> list[MachineState]:
    """Fleet seeded from config, with current setpoints/mode read back from KQL
    so operator- and auto-applied changes persist across runs."""
    fleet = default_fleet()
    current = io.latest_setpoints()
    for m in fleet:
        cur = current.get(m.machine_id)
        if cur:
            m.temp_sp, m.press_sp, m.cool_sp = cur["temp"], cur["press"], cur["cool"]
            m.mode = cur["mode"]
    return fleet


def _optimizer_iteration(io: KqlIO, m: MachineState, ts: datetime,
                         telemetry_sink: list) -> None:
    minutes = minutes_since_epoch(ts)

    def measure(tcmd, pcmd):
        tel = sample_telemetry(m, ts, minutes, tcmd, pcmd)
        return tel.defect_rate, tel

    decision, explore_rows = optimize_step(m, minutes, measure)
    telemetry_sink.extend(explore_rows)
    io.append_optimization(ts, m, decision)
    if decision.applied:
        io.append_setpoint(ts, m, "optimizer", decision.rationale)


def backfill(io: KqlIO, hours: float = 2.0, step_minutes: float = 1.5,
             optimize_every: int = 2) -> dict:
    """Generate a convergence history ending 'now'. Auto machines steer toward
    the optimum; the supervised machine holds (its recommendations accumulate for
    an operator to approve)."""
    states = build_states(io)
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    n_steps = int((hours * 60) / step_minutes)

    telemetry: list = []
    ts = start
    for i in range(n_steps):
        minutes = minutes_since_epoch(ts)
        for m in states:
            telemetry.append(sample_telemetry(m, ts, minutes))
            if i % optimize_every == 0:
                _optimizer_iteration(io, m, ts, telemetry)
        if len(telemetry) >= 400:
            io.append_telemetry(telemetry)
            telemetry = []
        ts += timedelta(minutes=step_minutes)

    if telemetry:
        io.append_telemetry(telemetry)

    # Persist final setpoint per machine (records converged/last state)
    for m in states:
        src = "optimizer" if m.mode == "auto" else "supervised-hold"
        io.append_setpoint(end, m, src, "Backfill final state")

    return {m.machine_id: {"mode": m.mode, "temp": round(m.temp_sp, 1),
                           "press": round(m.press_sp, 0)} for m in states}


def live_tick(io: KqlIO, windows: int = 3, step_seconds: float = 20.0) -> dict:
    """One scheduled real-time pass: emit a few fresh telemetry windows around
    'now' and run a single optimizer step per machine. Idempotent across runs
    because it always uses fresh timestamps."""
    states = build_states(io)
    now = datetime.now(timezone.utc)
    telemetry: list = []
    for w in range(windows):
        ts = now - timedelta(seconds=step_seconds * (windows - w))
        minutes = minutes_since_epoch(ts)
        for m in states:
            telemetry.append(sample_telemetry(m, ts, minutes))
    for m in states:
        _optimizer_iteration(io, m, now, telemetry)
    io.append_telemetry(telemetry)
    return {m.machine_id: {"mode": m.mode, "temp": round(m.temp_sp, 1),
                           "press": round(m.press_sp, 0)} for m in states}

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# --- Configuration (parameterized at deploy time by parameter.yml) -----------
QUERY_URI = "https://trd-8e59y4whercr4grn53.z7.kusto.fabric.microsoft.com"
KQL_DB    = "MfgRTI"

import notebookutils
def token_provider():
    for aud in ("kusto", "https://kusto.kusto.windows.net"):
        try:
            tok = notebookutils.credentials.getToken(aud)
            if tok:
                return tok
        except Exception:
            continue
    raise RuntimeError("Could not acquire a Kusto token via notebookutils")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# --- Run one closed-loop pass -----------------------------------------------
# First run on an empty database seeds ~2h of convergence history so the
# dashboard has depth immediately; subsequent runs do a single live tick.
io = RestKqlIO(QUERY_URI, KQL_DB, token_provider)
if io.count_telemetry() < 100:
    result = backfill(io, hours=2.0)
    print("Seeded backfill:", result)
else:
    result = live_tick(io)
    print("Live tick:", result)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
