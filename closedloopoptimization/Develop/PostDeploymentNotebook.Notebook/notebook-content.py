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
# Click **Run all**. This runs the ClosedLoopController once to seed a
# couple of hours of convergence history, then points you to the
# dashboard. Afterwards, schedule ClosedLoopController (every ~10 min)
# so the loop keeps running on its own.

# CELL ********************

# --- Seed the demo ----------------------------------------------------------
# Triggers ClosedLoopController once. On a fresh database it seeds ~2h of
# convergence history; the dashboard lights up within a couple of minutes.
import notebookutils
notebookutils.notebook.run("ClosedLoopController", 900)
print("Done. Open the ClosedLoopDashboard (Reporting) to watch the loop.")
print("Next: schedule ClosedLoopController every ~10 min to keep it live.")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
