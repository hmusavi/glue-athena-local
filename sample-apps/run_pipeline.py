"""
Orchestrates Glue jobs then queries results via Trino (local Athena).
"""

import subprocess
import time
import os
import shlex
import pandas as pd

from query_utils import run_trino_query

COMPOSE_CMD = shlex.split(os.getenv("DOCKER_COMPOSE_CMD", "docker compose"))
GLUE_SERVICE = os.getenv("GLUE_SERVICE", "glue")

def run_glue_job(job_file: str):
    print(f"\n{'='*60}\nRunning: {job_file}\n{'='*60}")
    result = subprocess.run([
        *COMPOSE_CMD, "exec", "-T", GLUE_SERVICE,
        "spark-submit",
        "--master", "local[*]",
        f"/home/hadoop/jobs/{job_file}",
    ])
    if result.returncode != 0:
        raise RuntimeError(f"{job_file} failed")
    print(f"✅ {job_file} done")

def query(sql: str, label: str):
    print(f"\n── {label} ──")
    cols, rows = run_trino_query(sql)
    df = pd.DataFrame(rows, columns=cols)
    print(df.to_string(index=False))
    return df

# ── Run Glue jobs ─────────────────────────────────────────────────────────────
run_glue_job("01_ingest_to_catalog.py")
run_glue_job("02_join_and_write.py")

# Give Trino a moment to reflect catalog changes
time.sleep(3)

# ── Query via Athena (Trino) ──────────────────────────────────────────────────
query(
    "SELECT * FROM glue.sales_db.customer_orders ORDER BY order_date",
    "All orders with customer details"
)

query(
    """
    SELECT customer_name, country,
           COUNT(*)    AS orders,
           SUM(amount) AS total_spent
    FROM glue.sales_db.customer_orders
    GROUP BY customer_name, country
    ORDER BY total_spent DESC
    """,
    "Spend by customer"
)

query(
    """
    SELECT country, SUM(amount) AS revenue
    FROM glue.sales_db.customer_orders
    GROUP BY country
    ORDER BY revenue DESC
    """,
    "Revenue by country"
)
