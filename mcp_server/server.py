"""
P3 · Task 5 — MCP server.

Exposes ONE governed tool, `query_metric`, over the dbt/MetricFlow semantic
layer. No raw-SQL tool exists — the agent can only ask for defined metrics
(principle 1: the allowlist IS the safety). Execution runs under the read-only
agent target (principle 7). Every call is logged through a standalone audit
module (principle 5). Tools are parameterised, not single-purpose (principle 4).

FAIL-CLOSED BOOT: the server verifies the read-only cage before serving a
single request. If the agent connection can read RAW.CUSTOMERS, the server
refuses to start. Governance is HARD on data.

W1 scope: native MCP, no agent framework, local/CLI host. The LLM connection
is Task 4-of-the-later-arc; this file is the tool surface + guardrails.

Run:  python server.py
"""

from __future__ import annotations
import sys

from mcp.server.fastmcp import FastMCP

from catalog import MetricCatalog
from mf_executor import run_metric_query, assert_read_only_cage, \
    MetricFlowError, CageBreachError
from audit import audit_log

mcp = FastMCP("schema-works-agent")

# ---- Fail-closed boot: prove the cage before anything else -----------------
try:
    assert_read_only_cage()
except CageBreachError as e:
    print(f"[REFUSING TO START] {e}", file=sys.stderr)
    sys.exit(1)

# Allowlist loaded once from the live semantic layer.
CATALOG = MetricCatalog.load()


@mcp.tool()
def query_metric(
    metric_names: list[str],
    group_by: list[str] | None = None,
    time_start: str | None = None,     # 'YYYY-MM-DD'
    time_end: str | None = None,       # 'YYYY-MM-DD'
    order_by: str | None = None,       # '-at_risk_mrr' for descending
    limit: int | None = None,
    team_context: str = "unknown",
) -> dict:
    """Query a governed metric from the dbt (MetricFlow) semantic layer.

    Only metrics and dimensions defined in the semantic layer can be queried;
    anything undefined is refused, not improvised. An honest "I can't group that
    yet" beats a confident wrong number.

    Args:
        metric_names: one or more metric names (see available_metrics on refusal).
        group_by:     dimensions/entities, e.g. ['customer__risk_band_label'].
        time_start / time_end: optional inclusive date bounds.
        order_by:     metric or dimension to sort by; prefix '-' for descending.
        limit:        max rows.
        team_context: which team is asking (recorded in the audit log).
    """
    ok, problem = CATALOG.validate(metric_names, group_by, order_by)
    if not ok:
        audit_log(metrics=metric_names, group_by=group_by, team=team_context,
                  status="refused", detail=problem, row_count=0)
        return {"status": "refused", "reason": problem,
                "available_metrics": CATALOG.metric_names,
                "available_dimensions": CATALOG.dimension_names}

    try:
        rows = run_metric_query(metric_names, group_by, time_start, time_end,
                                order_by, limit)
    except MetricFlowError as e:
        audit_log(metrics=metric_names, group_by=group_by, team=team_context,
                  status="error", detail=str(e), row_count=0)
        return {"status": "error", "reason": str(e)}

    audit_log(metrics=metric_names, group_by=group_by, team=team_context,
              status="ok", detail=None, row_count=len(rows))
    return {"status": "ok", "row_count": len(rows), "rows": rows}


if __name__ == "__main__":
    mcp.run()