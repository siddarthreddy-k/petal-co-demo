"""
P3 — Output validator (the LAST agent in the multi-agent chain).

The second half of the "governance sandwich":

    question -> INPUT guardrail -> query agent -> OUTPUT validator -> user
                (guardrail.py)     (agent.py)     (this file)

The input guardrail vets the REQUEST. This agent vets the ANSWER, just before it
reaches the human. Same posture as everything else: a SEPARATE, cheap LLM policy
agent that fails CLOSED — if it errors or returns anything unparseable, the
answer is WITHHELD, never shown by default.

It checks three things the query agent could get wrong even with a clean input:

  1. UNGROUNDED_NUMBER — the answer states a specific business figure (money,
     count, rate, %) as a MEASURED FACT that does not appear in the evidence
     (the actual rows the tool returned). This is the "stated a number it never
     queried" failure. Numbers explicitly framed as a suggestion/illustration
     (the SOFT-on-advice path) are fine.

  2. UNLABELED_ADVICE — the answer gives a recommendation/strategy but presents
     it as if it were measured fact, i.e. WITHOUT the "suggestion, not a measured
     result" labelling the system prompt requires. Grounded, clearly-labelled
     advice is fine.

  3. PII_LEAK — the answer exposes INDIVIDUAL customer identity. Per the row-
     level-out-by-design policy, that includes a customer_id value, a customer
     name, an email, phone, or address. Aggregates, segment/band breakdowns, and
     safe refusals are fine.

The validator is given the QUESTION, the ANSWER, and the EVIDENCE (a compact
summary of every governed query the agent actually ran, with the rows it got
back) so it can check groundedness against real data rather than guessing.

Design mirrors guardrail.py deliberately: same JSON contract, same fail-closed
except handler, same cheap model — so the two ends of the sandwich are symmetric
and easy to reason about together.
"""

from __future__ import annotations
import json

import anthropic

VALIDATOR_MODEL = "claude-haiku-4-5-20251001"   # cheap; classification only

# How many evidence rows to show the validator per query. Governed aggregate
# queries are tiny; this cap only guards against a pathological group-by.
_MAX_ROWS_PER_QUERY = 60

_POLICY = (
    "You are the OUTPUT VALIDATOR for a governed analytics agent serving the "
    "Petal & Co demo (a beauty/wellness subscription brand, money in GBP £). "
    "You are the final governance checkpoint BEFORE an answer reaches the user. "
    "You do NOT rewrite or answer the question — you only judge the answer that "
    "was produced, against the evidence that was actually queried.\n\n"

    "You will be given three things:\n"
    "  QUESTION — what the user asked.\n"
    "  ANSWER   — what the analytics agent wants to send back.\n"
    "  EVIDENCE — every governed query the agent actually ran this turn, with "
    "the metrics/dimensions requested and the rows returned. This is the ONLY "
    "data the agent legitimately has. If a figure is not derivable from EVIDENCE, "
    "the agent did not measure it.\n\n"

    "ALLOW the answer when it is faithful and safe. This INCLUDES:\n"
    "  - answers whose every stated figure traces to EVIDENCE (exact values, or "
    "sums/differences/obvious roundings of values that are present);\n"
    "  - recommendations/strategy that are grounded in the queried figures AND "
    "clearly labelled as a suggestion rather than a measured result;\n"
    "  - honest refusals or 'I can't measure that / that metric isn't defined' "
    "responses;\n"
    "  - answers that discuss customers only as AGGREGATES or segments (counts, "
    "risk bands, regions).\n\n"

    "BLOCK the answer if it falls into ANY category:\n"
    "  UNGROUNDED_NUMBER: it states a specific business figure (a money amount, "
    "customer/order count, rate, or percentage) as a MEASURED FACT that cannot "
    "be derived from EVIDENCE. A number that is explicitly presented as a "
    "suggestion, target, or illustration (not a measured result) is NOT a "
    "violation. Generic quantifiers with no invented figure ('most', 'a large "
    "share') are fine.\n"
    "  UNLABELED_ADVICE: it gives a recommendation, strategy, or suggestion but "
    "presents it AS measured fact — i.e. without making clear it is advice/"
    "opinion, not something the data directly says. If the answer already marks "
    "the advice as a suggestion (e.g. 'my suggestion, not a measured result'), "
    "ALLOW.\n"
    "  PII_LEAK: it exposes an INDIVIDUAL customer's identity — a specific "
    "customer_id value, a person's name, email, phone, or address. Row-level "
    "identity is out by design. (Aggregates and band/segment breakdowns are NOT "
    "a leak.)\n\n"

    "Judge ONLY the answer in front of you. Be precise: do not block grounded, "
    "clearly-labelled advice, and do not block safe refusals. When a genuine "
    "violation is present, block it.\n\n"

    "Respond with ONLY a JSON object, no other text:\n"
    '{"decision": "ALLOW" or "BLOCK", "category": "OK"|"UNGROUNDED_NUMBER"|'
    '"UNLABELED_ADVICE"|"PII_LEAK", "reason": "<one short sentence>"}'
)


def _summarize_evidence(evidence: list[dict] | None) -> str:
    """Render the queried figures into a compact, readable block for the judge.

    `evidence` is the list assembled in agent.ask(): one entry per governed
    tool call, each {metrics, group_by, status, row_count, rows}.
    """
    if not evidence:
        return "(no governed queries were run this turn — the agent has NO measured figures)"

    parts = []
    for i, ev in enumerate(evidence, 1):
        head = (
            f"Query {i}: metrics={ev.get('metrics')} "
            f"group_by={ev.get('group_by')} "
            f"status={ev.get('status')} rows={ev.get('row_count')}"
        )
        rows = ev.get("rows") or []
        if ev.get("status") == "ok" and rows:
            shown = rows[:_MAX_ROWS_PER_QUERY]
            body = json.dumps(shown, ensure_ascii=False)
            if len(rows) > _MAX_ROWS_PER_QUERY:
                body += f" …(+{len(rows) - _MAX_ROWS_PER_QUERY} more rows)"
            parts.append(head + "\n  rows: " + body)
        else:
            # refused / error / empty — no numbers legitimately available here
            detail = ev.get("detail")
            parts.append(head + (f"\n  detail: {detail}" if detail else ""))
    return "\n".join(parts)


def check(
    client: anthropic.Anthropic,
    question: str,
    answer: str,
    evidence: list[dict] | None,
) -> dict:
    """Return {'decision','category','reason'}. Fail-closed to BLOCK on error.

    Symmetry with guardrail.check(): same JSON contract, same cheap model, same
    fail-closed posture. On any exception or unparseable output, the answer is
    withheld (BLOCK), never shown.
    """
    user_content = (
        f"QUESTION:\n{question}\n\n"
        f"ANSWER:\n{answer}\n\n"
        f"EVIDENCE (the only data the agent actually queried this turn):\n"
        f"{_summarize_evidence(evidence)}"
    )
    try:
        resp = client.messages.create(
            model=VALIDATOR_MODEL,
            max_tokens=200,
            system=_POLICY,
            messages=[{"role": "user", "content": user_content}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        # tolerate accidental code fences
        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        if result.get("decision") not in {"ALLOW", "BLOCK"}:
            raise ValueError("no valid decision")
        result.setdefault("category", "OK")
        result.setdefault("reason", "")
        return result
    except Exception as e:                       # noqa: BLE001 - fail closed
        return {
            "decision": "BLOCK",
            "category": "ERROR",
            "reason": f"Output validator could not evaluate the answer ({e}); withheld by default.",
        }