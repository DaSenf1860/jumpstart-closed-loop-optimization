# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {}
# META }

# MARKDOWN ********************

# # Post-Deployment — seed & start the demo
# 
# Click **Run all**. This:
# 1. Runs **ClosedLoopController** once to seed ~2h of convergence history.
# 2. Deploys the **Rayfin operator console** app (Node + `rayfin up`, using
#    this notebook's Fabric identity — no interactive login).
# 
# Then open **ClosedLoopDashboard** (Reporting) to watch the loop, and
# schedule **ClosedLoopController** every ~10 min to keep it live.

# CELL ********************

# --- 1) Seed the closed loop -------------------------------------------------
# Runs ClosedLoopController once. On a fresh database it seeds ~2h of
# convergence history; the dashboard lights up within a couple of minutes.
import notebookutils
notebookutils.notebook.run("ClosedLoopController", 900)
print("Loop seeded. The ClosedLoopDashboard (Reporting) will show data shortly.")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# --- 2) Deploy the Rayfin operator console (optional, human-in-the-loop UI) ---
# Set DEPLOY_OPERATOR_CONSOLE = False to skip this and keep the demo to the
# autonomous RTI core only.
DEPLOY_OPERATOR_CONSOLE = True

REPO_URL = "https://github.com/DaSenf1860/jumpstart-closed-loop-optimization.git"
REPO_REF = "v1"   # tag or commit that contains the app source
APP_SUBPATH = "closedloopoptimization/optional-operator-console/app"
NODE_VERSION = "v20.18.1"

if DEPLOY_OPERATOR_CONSOLE:
    import os, subprocess, tarfile, time, urllib.request, re, notebookutils

    ctx = notebookutils.runtime.context
    ws_id = ctx.get("currentWorkspaceId") or ctx.get("workspaceId")
    print("Target workspace:", ws_id)

    def sh(cmd, cwd=None, env=None, timeout=2400):
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr

    # Install Node into /tmp
    t0 = time.time()
    tarball = f"/tmp/node-{NODE_VERSION}.tar.xz"
    urllib.request.urlretrieve(
        f"https://nodejs.org/dist/{NODE_VERSION}/node-{NODE_VERSION}-linux-x64.tar.xz", tarball)
    with tarfile.open(tarball) as tf:
        tf.extractall("/tmp")
    node_bin = f"/tmp/node-{NODE_VERSION}-linux-x64/bin"
    env = os.environ.copy()
    env["PATH"] = node_bin + ":" + env["PATH"]
    print("Node ready in %.0fs" % (time.time() - t0))

    # Clone the jumpstart repo (shallow) and locate the app
    subprocess.run(["rm", "-rf", "/tmp/clo_repo"])
    rc, so, se = sh(["git", "clone", "--branch", REPO_REF, "--depth", "1", REPO_URL, "/tmp/clo_repo"], env=env)
    if rc != 0:
        raise RuntimeError("git clone failed: " + se[-500:])
    app_dir = "/tmp/clo_repo/" + APP_SUBPATH
    print("App source:", app_dir, "exists:", os.path.isdir(app_dir))

    # Install dependencies
    t1 = time.time()
    rc, so, se = sh(["npm", "install", "--no-audit", "--no-fund"], cwd=app_dir, env=env, timeout=1200)
    print("npm install rc=%d in %.0fs" % (rc, time.time() - t1))
    if rc != 0:
        raise RuntimeError("npm install failed: " + se[-800:])

    # Deploy with the Rayfin CLI, using the notebook's Fabric token (no login UI)
    env["RAYFIN_TOKEN"] = notebookutils.credentials.getToken("pbi")
    env["RAYFIN_WORKSPACE_ID"] = ws_id
    t2 = time.time()
    rc, so, se = sh(["npx", "rayfin", "up", "--workspace-id", ws_id, "--yes"],
                    cwd=app_dir, env=env, timeout=2400)
    print("rayfin up rc=%d in %.0fs" % (rc, time.time() - t2))
    print(so[-2500:])
    if rc != 0:
        print("STDERR:", se[-1500:])
        raise RuntimeError("rayfin up failed (rc=%d)" % rc)

    m = re.search(r"https://[a-z0-9-]+\.webapp\.fabricapps\.net", so)
    if m:
        print("\nOperator console is live at:", m.group(0))
    print("\nOperator console deployed. To close the supervised loop (approve")
    print("recommendations from the app), also deploy the ClosedLoopBridge notebook")
    print("- see optional-operator-console/README.md.")
else:
    print("Skipped operator console deployment (DEPLOY_OPERATOR_CONSOLE = False).")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
