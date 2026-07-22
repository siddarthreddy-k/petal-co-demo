"""
P3 — Option A: standalone governed analytics agent.

Ties the LLM to the ONE governed tool (query_metric). Flow:
    NL question -> Claude picks query_metric + args -> catalog validates
    (fail-closed) -> mf_executor runs it under the READ-ONLY target -> result
    goes back to Claude -> Claude answers in plain English.

Every guarantee you already proved still holds: the agent can ONLY reach
defined metrics, queries run read-only (cannot see RAW/PII), and every call is
audited. The LLM never writes SQL and never sees a raw connection — it only
gets to fill in the parameters of one whitelisted tool.

Setup:
    set ANTHROPIC_API_KEY=sk-ant-...
    set AGENT_RO_KEY_PASSPHRASE=...      (as before)
Run from the dbt project root:
    python mcp_server/agent.py
"""

from __future__ import annotations
import json
import sys

# Load .env from the repo root (if present) BEFORE anything reads env vars.
from dotenv import load_dotenv
load_dotenv()

import anthropic

from catalog import MetricCatalog
from mf_executor import run_metric_query, assert_read_only_cage, \
    MetricFlowError, CageBreachError
from audit import audit_log
import guardrail
import output_validator

MODEL = "claude-haiku-4-5-20251001"   # small + cheap; fine for tool selection
MAX_TOKENS = 1024


# ---- Fail-closed boot: prove the cage before the agent can do anything -------
try:
    assert_read_only_cage()
except CageBreachError as e:
    print(f"[REFUSING TO START] {e}", file=sys.stderr)
    sys.exit(1)

CATALOG = MetricCatalog.load()

# The ONE tool the model is allowed to call. Its description lists exactly what
# exists, so the model grounds on the real catalog rather than inventing metrics.
TOOLS = [{
    "name": "query_metric",
    "description": (
        "Query a governed business metric from the semantic layer. This is the "
        "ONLY way to get numbers; you cannot write SQL. Only the metrics and "
        "dimensions listed below exist — do not invent others.\n\n"
        f"Available metrics: {', '.join(CATALOG.metric_names)}\n"
        f"Available dimensions (for group_by): {', '.join(CATALOG.dimension_names)}"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "metric_names": {"type": "array", "items": {"type": "string"},
                             "description": "One or more metric names from the list."},
            "group_by": {"type": "array", "items": {"type": "string"},
                         "description": "Optional dimensions, e.g. customer__risk_band_label."},
            "order_by": {"type": "string",
                         "description": "Metric/dimension to sort by; prefix '-' for descending."},
            "limit": {"type": "integer", "description": "Max rows."},
        },
        "required": ["metric_names"],
    },
}]

SYSTEM = (
    "You are Schema Works' governed analytics agent for the Petal & Co demo "
    "(a beauty/wellness subscription brand). Money is in GBP (£).\n\n"

    "You operate under one governing principle: HARD ON DATA, SOFT ON ADVICE.\n\n"

    "== HARD ON DATA (never bend this) ==\n"
    "- Every NUMBER or FACT you state must come from the query_metric tool. "
    "NEVER invent, estimate, or guess a figure. Not even a plausible-sounding one.\n"
    "- If a metric to answer a factual question does not exist, say so plainly "
    "and name what you CAN measure. Do not substitute a made-up number.\n"
    "- Do not fabricate data that isn't in the semantic layer (e.g. there is no "
    "offer/campaign performance data — never invent offer results, conversion "
    "rates, or historical figures for things you cannot query).\n\n"

    "== SOFT ON ADVICE (you MAY advise, but only grounded) ==\n"
    "When asked for recommendations, strategy, or suggestions (e.g. 'what should "
    "we do about churn?', 'suggest welcome offers'), you ARE allowed to help — "
    "but you must GROUND FIRST:\n"
    "  1. Before advising, call query_metric to pull the REAL figures relevant "
    "to the question (e.g. new-customer counts, AOV, revenue per customer, "
    "risk-band breakdown). Advice must be built on actual data, not vibes.\n"
    "  2. State the grounding figures you pulled, then give your reasoning.\n"
    "  3. LABEL every recommendation clearly as advice, not measured fact. Use "
    "explicit language like 'Based on the data, my suggestion (not a measured "
    "result) is…'. The reader must always be able to tell a QUERIED NUMBER from "
    "a SUGGESTION.\n\n"

    "== STYLE ==\n"
    "Answer concisely in plain English. Cite the actual figures you queried. "
    "When you cross from data into advice, mark the transition explicitly so the "
    "line between fact and opinion is never blurred."
)


def _run_tool(tool_input: dict, team_context: str = "cli") -> dict:
    """Validate against the allowlist, then execute read-only. Same guarantees
    as the MCP server's query_metric. `team_context` identifies WHO asked and
    is written to the audit log (e.g. a Slack user id)."""
    metric_names = tool_input.get("metric_names", [])
    group_by = tool_input.get("group_by")
    order_by = tool_input.get("order_by")
    limit = tool_input.get("limit")

    ok, problem = CATALOG.validate(metric_names, group_by, order_by)
    if not ok:
        audit_log(metrics=metric_names, group_by=group_by, team=team_context,
                  status="refused", detail=problem, row_count=0)
        return {"status": "refused", "reason": problem}

    try:
        rows = run_metric_query(metric_names, group_by, None, None, order_by, limit)
    except MetricFlowError as e:
        audit_log(metrics=metric_names, group_by=group_by, team=team_context,
                  status="error", detail=str(e), row_count=0)
        return {"status": "error", "reason": str(e)}

    audit_log(metrics=metric_names, group_by=group_by, team=team_context,
              status="ok", detail=None, row_count=len(rows))
    return {"status": "ok", "row_count": len(rows), "rows": rows}


def ask(client: anthropic.Anthropic, question: str, team_context: str = "cli",
        context: str = "") -> str:
    """One question -> answer, wrapped in the full GOVERNANCE SANDWICH:

        INPUT guardrail  ->  query agent  ->  OUTPUT validator  ->  user

    Agent 1 (guardrail.py) vets the REQUEST; only an ALLOW proceeds. Agent 2
    (this loop) answers via the one governed tool. Agent 3 (output_validator.py)
    vets the ANSWER against the figures actually queried before it is shown —
    fail-closed, so a bad answer is withheld, not sent. `team_context` is
    recorded against every governed query and policy decision in the audit log.

    `context` is OPTIONAL background (e.g. a Slack thread) given to the query
    agent for grounding. It is deliberately NOT sent to the input guardrail: the
    guardrail judges the actual QUESTION, so conversational thread chatter can't
    trip it, and the output validator still judges the answer against the real
    question and the queried evidence.
    """
    # --- Agent 1: input guardrail (fail-closed) ---------------------------
    verdict = guardrail.check(client, question)
    if verdict["decision"] != "ALLOW":
        audit_log(metrics=[], group_by=None, team=team_context,
                  status="blocked", detail=f'{verdict["category"]}: {verdict["reason"]}',
                  row_count=0, question=question)
        print(f"   [guardrail] BLOCK ({verdict['category']}): {verdict['reason']}")
        return (f"I can't help with that request. "
                f"({verdict['category']}: {verdict['reason']})")
    print(f"   [guardrail] ALLOW")

    # --- Agent 2: query agent --------------------------------------------
    if context:
        first_message = (
            "Background — recent Slack thread (context only; may be "
            "conversational and not all relevant):\n"
            f"{context}\n\n---\nQuestion to answer now:\n{question}"
        )
    else:
        first_message = question
    messages = [{"role": "user", "content": first_message}]
    # Every governed query run this turn, captured so the output validator can
    # check the answer's figures against what was ACTUALLY measured.
    evidence: list[dict] = []

    answer = ""
    while True:
        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            system=SYSTEM, tools=TOOLS, messages=messages,
        )

        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    print(f"   [tool] query_metric({json.dumps(block.input)})")
                    result = _run_tool(block.input, team_context)
                    evidence.append({
                        "metrics": block.input.get("metric_names"),
                        "group_by": block.input.get("group_by"),
                        "status": result.get("status"),
                        "row_count": result.get("row_count", 0),
                        "rows": result.get("rows"),
                        "detail": result.get("reason"),
                    })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        # No tool call -> the model's final answer
        answer = "".join(b.text for b in resp.content if b.type == "text")
        break

    # --- Agent 3: output validator (fail-closed) -------------------------
    queried_metrics = [m for ev in evidence for m in (ev.get("metrics") or [])]
    check = output_validator.check(client, question, answer, evidence)
    if check["decision"] != "ALLOW":
        audit_log(metrics=queried_metrics, group_by=None, team=team_context,
                  status="blocked_output",
                  detail=f'{check["category"]}: {check["reason"]}',
                  row_count=0, question=question)
        print(f"   [validator] BLOCK ({check['category']}): {check['reason']}")
        return (
            "I generated an answer but it did not pass output validation, so I'm "
            "withholding it — governance is fail-closed on the answer too. "
            f"(Reason — {check['category']}: {check['reason']}) "
            "Try rephrasing, or ask for the underlying figures directly."
        )
    print(f"   [validator] ALLOW")
    audit_log(metrics=queried_metrics, group_by=None, team=team_context,
              status="answered", detail=None,
              row_count=sum(ev.get("row_count", 0) for ev in evidence),
              question=question)
    return answer


def main():
    client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY from env
    print("Schema Works governed analytics agent (Petal & Co). "
          "Ask a question, or 'quit'.\n")
    while True:
        try:
            q = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in {"quit", "exit", ""}:
            break
        print(ask(client, q) + "\n")


if __name__ == "__main__":
    main()