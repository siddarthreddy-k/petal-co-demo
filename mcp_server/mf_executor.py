"""
P3 · Task 7 — MetricFlow execution layer (Option A: robust CLI integration).

Runs `mf query` as a subprocess, UNDER THE READ-ONLY agent target, and returns
structured rows. Two correctness points that are easy to get catastrophically
wrong:

  1. `mf query` IGNORES `--target`. It reads the target from the DBT_TARGET
     environment variable. If you set neither, mf runs as your DEFAULT target
     (SYSADMIN here), which CAN read RAW — a silent, invisible cage bypass.
     So every subprocess here runs with DBT_TARGET=agent_ro in its env.

  2. `dbt` (used for the boot cage check) DOES honour --target. So the cage
     check passes --target explicitly AND sets the env var. Belt and suspenders.

We use `--csv <file>` (supported on dbt Core) so results are parsed cleanly
instead of scraped from an ASCII table.
"""

from __future__ import annotations
import csv
import os
import subprocess
import tempfile

# The read-only dbt target created in Task 4 (service user, key-pair, RO role).
RO_TARGET = os.environ.get("AGENT_RO_TARGET", "agent_ro")

# Where profiles.yml lives. For this repo it sits in the project root; mf run
# from the project root finds it, but we set it explicitly to be safe.
PROFILES_DIR = os.environ.get("DBT_PROFILES_DIR", os.getcwd())


class MetricFlowError(Exception):
    """A query failed inside MetricFlow / the warehouse."""


class CageBreachError(Exception):
    """The read-only cage is NOT in effect. The server must not run."""


def _agent_env() -> dict:
    """Environment that forces every mf/dbt subprocess onto the RO target."""
    env = dict(os.environ)
    env["DBT_TARGET"] = RO_TARGET          # the var mf actually reads
    env["DBT_PROFILES_DIR"] = PROFILES_DIR
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _resolve(exe: str) -> str:
    """Full path to an executable, so Windows finds `mf.exe`/`dbt.exe` the same
    way your shell does (bare names don't resolve via PATHEXT under subprocess).
    """
    import shutil
    found = shutil.which(exe)
    if not found:
        raise MetricFlowError(
            f"`{exe}` not found on PATH. Activate the (dbt) env before running."
        )
    return found


def _run(cmd: list[str]):
    """Run a subprocess (list form, no shell) with the RO env. The first element
    is the executable name (`mf` or `dbt`), resolved to a full path here.
    """
    resolved = [_resolve(cmd[0])] + cmd[1:]
    return subprocess.run(resolved, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=_agent_env())

def _run_plain(cmd: list[str]):
    """Run a metadata command (e.g. `mf list`) WITHOUT forcing the RO target.
    Listing metric/dimension NAMES reads the semantic manifest — it's metadata,
    not warehouse data — so it doesn't need the cage. The cage applies to
    `mf query` (real numbers), which goes through _run() below.
    """
    resolved = [_resolve(cmd[0])] + cmd[1:]
    plain_env = dict(os.environ)
    plain_env["PYTHONUTF8"] = "1"
    plain_env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(resolved, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=plain_env)



def assert_read_only_cage() -> None:
    """Boot-time fail-closed check. Prove the agent connection CANNOT read RAW.

    Reuses the exact mechanism validated by hand in Task 4: a dbt query against
    RAW under the agent_ro target. If it SUCCEEDS, the target routing is wrong
    (we're running as an over-privileged role) and we refuse to start.
    """
    proc = _run(
        ["dbt", "show", "--quiet", "--inline",
         "select CUSTOMER_ID from PETAL_CO_DW.RAW.CUSTOMERS",
         "--target", RO_TARGET, "--limit", "1"]
    )
    combined = (proc.stdout + proc.stderr).lower()

    if proc.returncode == 0:
        # The RAW read WORKED. Cage is open. Stop everything.
        raise CageBreachError(
            "SECURITY: agent connection can read PETAL_CO_DW.RAW.CUSTOMERS. "
            "The read-only cage is not in effect — refusing to start. "
            "Check that DBT_TARGET/agent_ro is routing to SCHEMA_WORKS_AGENT_RO."
        )
    if "not authorized" in combined or "does not exist" in combined:
        return  # correct: RAW is invisible to the agent
    # Failed for some other reason (bad creds, warehouse asleep, etc.)
    raise CageBreachError(
        "Cage check could not be verified (unexpected error): "
        + (proc.stderr.strip() or proc.stdout.strip())
    )


def run_metric_query(
    metric_names: list[str],
    group_by: list[str] | None = None,
    time_start: str | None = None,   # 'YYYY-MM-DD'
    time_end: str | None = None,     # 'YYYY-MM-DD'
    order_by: str | None = None,     # e.g. '-avg_churn_probability' (desc)
    limit: int | None = None,
) -> list[dict]:
    """Run a governed metric query via `mf query`; return rows as list[dict]."""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        csv_path = tmp.name

    cmd = ["mf", "query", "--metrics", ",".join(metric_names), "--csv", csv_path]
    if group_by:
        cmd += ["--group-by", ",".join(group_by)]
    if time_start:
        cmd += ["--start-time", time_start]
    if time_end:
        cmd += ["--end-time", time_end]
    if order_by:
        cmd += ["--order", order_by]      # '--order' confirmed working in 0.211.0
    if limit:
        cmd += ["--limit", str(limit)]

    try:
        proc = _run(cmd)
        if proc.returncode != 0:
            # MetricFlow fails closed on undefined metrics/dims/joins — surface it.
            raise MetricFlowError(proc.stderr.strip() or proc.stdout.strip()
                                  or "mf query failed with no message.")
        with open(csv_path, newline="") as fh:
            return list(csv.DictReader(fh))
    finally:
        try:
            os.unlink(csv_path)
        except OSError:
            pass