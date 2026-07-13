# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {}
# META }

# MARKDOWN ********************

# # ClosedLoopBridge — KQL <-> Rayfin SQL
# 
# Closes the supervised loop and feeds the operator console:
# - **SQL -> KQL**: applies pending operator setpoint commands to the
#   MfgRTI control channel.
# - **KQL -> SQL**: republishes live KPIs / recommendations / trend into
#   the Rayfin app's SQL layer.
# 
# Uses the JVM's built-in SQL JDBC driver + the notebook's Fabric token
# (no pyodbc). **Schedule every ~5 minutes** once the operator console is
# deployed. Requires the Rayfin app (SQL Database) to exist first.

# CELL ********************

# ===== bridge_spark.py — KQL<->SQL bridge (Spark JDBC) =====
"""
bridge_spark.py — Fabric/Spark-native version of the KQL <-> Rayfin SQL bridge.

Reaches the Rayfin Fabric SQL Database through the JVM's built-in Microsoft SQL
Server JDBC driver (via Py4J), using an Entra access token — so it needs NO
`pyodbc` and NO system ODBC driver, and runs in a plain Fabric notebook.

KQL is read/written over the REST API with `requests` (available in Fabric).

Same behaviour as bridge.py:
  SQL -> KQL : apply pending SetpointCommands to MfgRTI Setpoints (closes loop)
  KQL -> SQL : publish fn_LiveKpis / fn_PendingRecommendations / fn_DefectTrend
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import requests

TREND_WINDOW_MIN = 120
TREND_BIN_MIN = 3

ENTITIES: dict[str, list[str]] = {
    "MachineSnapshot": ["MachineSnapshot", "MachineSnapshots"],
    "Recommendation": ["Recommendation", "Recommendations"],
    "TrendPoint": ["TrendPoint", "TrendPoints"],
    "SetpointCommand": ["SetpointCommand", "SetpointCommands"],
    "LoopEvent": ["LoopEvent", "LoopEvents"],
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _uuid() -> str:
    return str(uuid.uuid4())


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def sql_lit(v: Any) -> str:
    """Format a Python value as a T-SQL literal (data is internal/controlled)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, datetime):
        return "'" + v.strftime("%Y-%m-%dT%H:%M:%S") + "'"
    return "'" + str(v).replace("'", "''") + "'"


def _parse_dt(v: Any) -> datetime:
    s = str(v).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# KQL over REST
# ---------------------------------------------------------------------------
class KqlClient:
    def __init__(self, query_uri: str, database: str, token_provider: Callable[[], str]):
        self.query_uri = query_uri.rstrip("/")
        self.database = database
        self.token_provider = token_provider

    def _post(self, endpoint: str, csl: str) -> dict:
        headers = {"Authorization": f"Bearer {self.token_provider()}",
                   "Content-Type": "application/json"}
        r = requests.post(f"{self.query_uri}/v1/rest/{endpoint}",
                          headers=headers, json={"db": self.database, "csl": csl}, timeout=60)
        r.raise_for_status()
        return r.json()

    def query(self, csl: str) -> list[dict]:
        table = self._post("query", csl)["Tables"][0]
        cols = [c["ColumnName"] for c in table["Columns"]]
        return [dict(zip(cols, row)) for row in table["Rows"]]

    def append_setpoint(self, machine_id: str, temp: float, press: float, cool: float,
                        mode: str, note: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        note_s = note.replace("'", "''")
        cmd = (".set-or-append Setpoints <| datatable(Timestamp:datetime, MachineId:string, "
               "TempSetpoint:real, PressureSetpoint:real, CoolingTimeS:real, Source:string, "
               "Mode:string, Note:string)["
               f"datetime({ts}Z),'{machine_id}',{temp},{press},{cool},'operator','{mode}','{note_s}']")
        self._post("mgmt", cmd)


# ---------------------------------------------------------------------------
# Rayfin SQL over Spark JVM JDBC (Py4J)
# ---------------------------------------------------------------------------
class SparkSql:
    """Talks to the Fabric SQL Database via the JVM's MS SQL JDBC driver using an
    access token. `spark` is the notebook SparkSession; `token_provider` returns
    a bearer token whose audience is accepted by the SQL endpoint."""

    def __init__(self, spark, server: str, database: str, token_provider: Callable[[], str]):
        self.spark = spark
        self.jvm = spark._sc._gateway.jvm
        self.server = server
        self.database = database
        self.token_provider = token_provider
        self._conn = None
        self._tables: dict[str, str] = {}
        self._cols: dict[str, dict[str, str]] = {}

    def conn(self):
        if self._conn is None:
            url = (f"jdbc:sqlserver://{self.server}:1433;database={self.database};"
                   "encrypt=true;trustServerCertificate=false;loginTimeout=30;")
            props = self.jvm.java.util.Properties()
            props.setProperty("accessToken", self.token_provider())
            self._conn = self.jvm.java.sql.DriverManager.getConnection(url, props)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # -- low-level ----------------------------------------------------------
    def select(self, sql: str) -> list[dict]:
        st = self.conn().createStatement()
        rs = st.executeQuery(sql)
        md = rs.getMetaData()
        n = md.getColumnCount()
        cols = [md.getColumnLabel(i + 1) for i in range(n)]
        out: list[dict] = []
        while rs.next():
            out.append({cols[i]: rs.getObject(i + 1) for i in range(n)})
        rs.close()
        st.close()
        return out

    def execute(self, sql: str) -> int:
        st = self.conn().createStatement()
        try:
            return st.executeUpdate(sql)
        finally:
            st.close()

    # -- schema discovery ---------------------------------------------------
    def discover(self) -> None:
        if self._tables:
            return
        rows = self.select("SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME "
                           "FROM INFORMATION_SCHEMA.COLUMNS")
        grouped: dict[str, list[str]] = {}
        for r in rows:
            key = f"{r['TABLE_SCHEMA']}.{r['TABLE_NAME']}"
            grouped.setdefault(key, []).append(r["COLUMN_NAME"])
        for entity, candidates in ENTITIES.items():
            for key, columns in grouped.items():
                tname = key.split(".", 1)[1]
                if any(tname.lower() == c.lower() for c in candidates):
                    self._tables[entity] = "[" + key.replace(".", "].[") + "]"
                    self._cols[entity] = {c.lower(): c for c in columns}
                    break
            if entity not in self._tables:
                raise RuntimeError(f"Table for {entity} not found. Saw: {sorted(grouped)}")

    def col(self, entity: str, field: str) -> str:
        actual = self._cols[entity].get(field.lower())
        if not actual:
            raise KeyError(f"{entity}.{field} missing; has {list(self._cols[entity].values())}")
        return f"[{actual}]"

    def table(self, entity: str) -> str:
        return self._tables[entity]


# ---------------------------------------------------------------------------
# KQL -> SQL
# ---------------------------------------------------------------------------
def publish_snapshots(kql: KqlClient, sql: SparkSql) -> int:
    rows = kql.query("fn_LiveKpis()")
    e, t = "MachineSnapshot", None
    t = sql.table("MachineSnapshot")
    for r in rows:
        mid = r["MachineId"]
        vals = {
            "lineId": r.get("LineId", ""), "product": r.get("Product", ""),
            "mode": r.get("Mode") or "auto", "status": r.get("Status") or "healthy",
            "currentDefectRate": _num(r.get("CurrentDefectRate")),
            "tempC": _num(r.get("TempC")), "pressureBar": _num(r.get("PressureBar")),
            "tempSetpoint": _num(r.get("TempSetpoint")), "pressureSetpoint": _num(r.get("PressureSetpoint")),
            "coolingTimeS": _num(r.get("CoolingTimeS"), 12.0),
            "parts": int(_num(r.get("Parts"))), "defects": int(_num(r.get("Defects"))),
            "vibration": _num(r.get("Vibration")), "updatedAt": datetime.now(timezone.utc),
        }
        exists = sql.select(f"SELECT {sql.col(e,'id')} AS id FROM {t} "
                            f"WHERE {sql.col(e,'machineId')} = {sql_lit(mid)}")
        if exists:
            sets = ", ".join(f"{sql.col(e,k)} = {sql_lit(v)}" for k, v in vals.items())
            sql.execute(f"UPDATE {t} SET {sets} WHERE {sql.col(e,'machineId')} = {sql_lit(mid)}")
        else:
            cols = [sql.col(e, "id"), sql.col(e, "machineId")] + [sql.col(e, k) for k in vals]
            lits = [sql_lit(_uuid()), sql_lit(mid)] + [sql_lit(v) for v in vals.values()]
            sql.execute(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join(lits)})")
    return len(rows)


def publish_recommendations(kql: KqlClient, sql: SparkSql) -> int:
    rows = kql.query("fn_PendingRecommendations()")
    e = "Recommendation"
    t = sql.table(e)
    sql.execute(f"DELETE FROM {t} WHERE {sql.col(e,'status')} = 'pending'")
    for r in rows:
        cols = [sql.col(e, c) for c in ("id", "machineId", "observedDefectRate", "recommendedTemp",
                                        "recommendedPressure", "expectedDefectRate", "rationale",
                                        "status", "createdAt")]
        lits = [sql_lit(_uuid()), sql_lit(r["MachineId"]), sql_lit(_num(r.get("ObservedDefectRate"))),
                sql_lit(_num(r.get("RecommendedTemp"))), sql_lit(_num(r.get("RecommendedPressure"))),
                sql_lit(_num(r.get("ExpectedDefectRate"))), sql_lit((r.get("Rationale") or "")[:500]),
                sql_lit("pending"), sql_lit(datetime.now(timezone.utc))]
        sql.execute(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join(lits)})")
    return len(rows)


def publish_trend(kql: KqlClient, sql: SparkSql) -> int:
    rows = kql.query(f"fn_DefectTrend({TREND_WINDOW_MIN}, {TREND_BIN_MIN})")
    e = "TrendPoint"
    t = sql.table(e)
    sql.execute(f"DELETE FROM {t}")
    for r in rows:
        cols = [sql.col(e, c) for c in ("id", "machineId", "ts", "defectRate", "tempSetpoint")]
        lits = [sql_lit(_uuid()), sql_lit(r["MachineId"]), sql_lit(_parse_dt(r["Timestamp"])),
                sql_lit(_num(r.get("DefectRate"))), sql_lit(_num(r.get("TempSetpoint")))]
        sql.execute(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join(lits)})")
    return len(rows)


# ---------------------------------------------------------------------------
# SQL -> KQL (apply operator commands)
# ---------------------------------------------------------------------------
def apply_commands(kql: KqlClient, sql: SparkSql) -> int:
    e = "SetpointCommand"
    t = sql.table(e)
    le = "LoopEvent"
    lt = sql.table(le)
    pending = sql.select(
        f"SELECT {sql.col(e,'id')} AS id, {sql.col(e,'machineId')} AS machineId, "
        f"{sql.col(e,'kind')} AS kind, {sql.col(e,'tempSetpoint')} AS temp, "
        f"{sql.col(e,'pressureSetpoint')} AS press, {sql.col(e,'coolingTimeS')} AS cool, "
        f"{sql.col(e,'mode')} AS mode, {sql.col(e,'requestedBy')} AS requestedBy, "
        f"{sql.col(e,'note')} AS note "
        f"FROM {t} WHERE {sql.col(e,'status')} = 'requested'")
    applied = 0
    for row in pending:
        cmd_id = str(row["id"])
        mid = str(row["machineId"])
        try:
            note_txt = f"{row.get('note') or 'operator command'} (by {row.get('requestedBy')})"
            kql.append_setpoint(mid, _num(row.get("temp")), _num(row.get("press")),
                                _num(row.get("cool"), 12.0), str(row.get("mode")), note_txt)
            sql.execute(f"UPDATE {t} SET {sql.col(e,'status')} = 'applied', "
                        f"{sql.col(e,'appliedAt')} = {sql_lit(datetime.now(timezone.utc))} "
                        f"WHERE {sql.col(e,'id')} = {sql_lit(cmd_id)}")
            msg = (f"Applied {row.get('kind')} to {mid}: T {_num(row.get('temp')):.1f}C "
                   f"P {_num(row.get('press')):.0f}bar mode={row.get('mode')} "
                   f"(operator {row.get('requestedBy')})")
            cols = [sql.col(le, c) for c in ("id", "machineId", "ts", "kind", "message")]
            lits = [sql_lit(_uuid()), sql_lit(mid), sql_lit(datetime.now(timezone.utc)),
                    sql_lit("applied"), sql_lit(msg[:500])]
            sql.execute(f"INSERT INTO {lt} ({', '.join(cols)}) VALUES ({', '.join(lits)})")
            applied += 1
        except Exception:
            try:
                sql.execute(f"UPDATE {t} SET {sql.col(e,'status')} = 'error' "
                            f"WHERE {sql.col(e,'id')} = {sql_lit(cmd_id)}")
            except Exception:
                pass
    return applied


def run_once(spark, cfg: dict, kusto_token: Callable[[], str],
             sql_token: Callable[[], str]) -> dict:
    kql = KqlClient(cfg["queryUri"], cfg["kqlDbName"], kusto_token)
    sql = SparkSql(spark, cfg["sqlServer"], cfg["sqlDatabase"], sql_token)
    try:
        sql.discover()
        applied = apply_commands(kql, sql)
        snaps = publish_snapshots(kql, sql)
        recs = publish_recommendations(kql, sql)
        trend = publish_trend(kql, sql)
        return {"snapshots": snaps, "recommendations": recs,
                "trend_points": trend, "commands_applied": applied}
    finally:
        sql.close()

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# --- Discover config at runtime (KQL DB + Rayfin app SQL Database) -----------
import notebookutils, requests

ctx = notebookutils.runtime.context
WS = ctx.get("currentWorkspaceId") or ctx.get("workspaceId")
FAB = notebookutils.credentials.getToken("pbi")
H = {"Authorization": "Bearer " + FAB}
API = "https://api.fabric.microsoft.com/v1/workspaces/" + WS

# KQL database query URI (Eventhouse "MfgRTI")
dbs = requests.get(API + "/kqlDatabases", headers=H, timeout=60).json()["value"]
mfg = next(d for d in dbs if d["displayName"] == "MfgRTI")
QUERY_URI = mfg["properties"]["queryServiceUri"]

# Rayfin app SQL Database (deployed by the operator console)
items = requests.get(API + "/items", headers=H, timeout=60).json()["value"]
sqldb_item = next(i for i in items if i["type"] == "SQLDatabase")
sqldb = requests.get(API + "/sqlDatabases/" + sqldb_item["id"], headers=H, timeout=60).json()
SQL_SERVER = sqldb["properties"]["serverFqdn"].split(",")[0]
SQL_DB = sqldb["properties"]["databaseName"]

CFG = {"queryUri": QUERY_URI, "kqlDbName": "MfgRTI",
       "sqlServer": SQL_SERVER, "sqlDatabase": SQL_DB}
print("Bridge config:", {k: (v[:40] if k == "queryUri" else v) for k, v in CFG.items()})

def kusto_token():
    return notebookutils.credentials.getToken("kusto")

# Fabric SQL endpoints accept the Power BI / Fabric token.
def sql_token():
    return notebookutils.credentials.getToken("pbi")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# --- Run one bridge pass -----------------------------------------------------
# SQL -> KQL applies pending operator commands; KQL -> SQL republishes KPIs.
result = run_once(spark, CFG, kusto_token, sql_token)
print("Bridge pass complete:", result)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
