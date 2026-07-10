# Closed-Loop Optimization on Microsoft Fabric

A **live, self-optimizing manufacturing line** built entirely on Microsoft Fabric
Real-Time Intelligence. A fleet of injection-molding machines streams sensor data;
an **SPSA optimizer** continuously tunes each machine's setpoints toward a *moving*
quality target; and the whole control loop closes in real time — autonomously for
"auto" machines, with human approval for "supervised" ones.

> **Measure → Analyze → Decide → Act → repeat.** The system changes its own inputs
> and you watch quality (defect rate) improve as a direct result.

## What's inside

- **MfgRTI (Eventhouse / KQL DB)** — telemetry stream, a `Setpoints` control
  channel, an optimizer decision log, and KPI functions (`fn_LiveKpis`,
  `fn_DefectTrend`, `fn_FleetSummary`, `fn_PendingRecommendations`).
- **ClosedLoopController (Notebook)** — a **digital-twin plant** (hidden, drifting
  optimum) driven by an **SPSA optimizer** that only sees the defect rate and
  steers temperature/pressure downhill within a safe envelope. Seeds ~2h of
  history on first run, then does one live tick per run.
- **DefectRateAlert (Activator)** — emails when any machine's defect rate crosses
  above 8%.
- **ClosedLoopDashboard (Real-Time Dashboard)** — fleet defect-rate trend (with an
  8% threshold line), live KPIs, optimizer activity, and pending recommendations.
- **PostDeploymentNotebook** — one click to seed and start the demo.

## Deploy it

Everything here is a Fabric workspace definition deployable with
[fabric-cicd](https://microsoft.github.io/fabric-cicd/latest/).

1. Clone this repo and `cd closedloopoptimization`.
2. `pip install fabric-cicd azure-identity`
3. `az login`
4. Edit `deploy.py` and set your target `WORKSPACE_ID`.
5. `python deploy.py` — publishes the Eventhouse/KQL DB, notebooks, dashboard,
   and Activator. `parameter.yml` rewrites the cluster URI and item ids to your
   workspace automatically (uses the `PROD` environment).

## Start it

Open **PostDeploymentNotebook** in the workspace and **Run all**. It runs the
optimizer once to seed a couple of hours of convergence history. Within a minute
or two, open **ClosedLoopDashboard** (Reporting) and watch the auto machines
converge toward ~3% defects while the supervised machine's recommendation shows
up in the *Pending recommendations* tile.

To keep the loop running, **schedule `ClosedLoopController`** every ~10 minutes
(Notebook → Schedule).

## The story to tell

- **Auto machines** self-optimize with no human involvement.
- **The supervised machine** only *recommends* — a human decides. Its
  recommendations accumulate in the dashboard until approved.
- The optimum **drifts continuously**, so the loop never "finishes" — it
  perpetually re-converges, just like real process control fighting tool wear and
  material variation.

## Optional extension — Operator Console (human-in-the-loop)

The full demo includes a **Rayfin operator console** (a Fabric-authenticated React
app) and a **KQL ⇄ SQL bridge** that let an operator *approve* a supervised
machine's recommendation with one click — closing the loop by hand. Rayfin apps
are **not** deployable via fabric-cicd, so they're not part of this repo. See
`optional-operator-console/README.md` for how to add them.

## Architecture

```
ClosedLoopController (SPSA optimizer + digital twin)
        |  telemetry + auto setpoints, recommendations
        v
   MfgRTI Eventhouse/KQL  --fn_*()-->  ClosedLoopDashboard (live wall)
                                       DefectRateAlert (email on >8%)
```
