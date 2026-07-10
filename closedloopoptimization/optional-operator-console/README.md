# Optional: Operator Console + KQL⇄SQL Bridge (human-in-the-loop)

This extension adds the **supervised** half of the closed loop: a Fabric-hosted
**Rayfin operator console** where a human approves a machine's optimizer
recommendation, and a **bridge** that applies that decision back into the KQL
control channel.

**Why it's separate:** Rayfin apps (AppBackend + SQL Database) are **not**
deployable via fabric-cicd, so they can't live in this git-format repo.

## What it adds
- **Operator Console (React + Rayfin):** live KPI cards, auto⇄supervised toggle,
  one-click *Approve & apply*, manual override, and a loop activity feed.
- **ClosedLoopBridge (Spark notebook):** each pass applies pending operator
  `SetpointCommand`s to the KQL `Setpoints` table (Source='operator'), then
  republishes `fn_LiveKpis` / `fn_PendingRecommendations` / `fn_DefectTrend` into
  the app's SQL layer. It uses the JVM's built-in SQL JDBC driver + a Fabric
  token (getToken("pbi")) — no pyodbc.

## How to add it
1. Deploy the Rayfin app (`app/` in the source project) with the Rayfin CLI into
   the same workspace: `npx rayfin up --workspace-id <ws-id>`.
2. Deploy `ClosedLoopBridge` as a Fabric notebook and set its `sqlServer` /
   `sqlDatabase` to the app's SQL Database connection (Fabric portal → the app's
   SQL Database → connection string). Schedule it every ~15 min.
3. In the console, approve the supervised machine's recommendation and watch its
   defect rate drop in the dashboard.

The bridge source and the full app live in the source project; this folder is a
pointer so the deployable core stays self-contained.
