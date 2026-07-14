"""
Standalone audit module (principle 5).

Kept SEPARATE from the agent so the trail stays complete across channels
(CLI now, Slack/UI later) and a future guardrail agent can share it. Every
tool call — success, refusal, or error — writes one row.

W1 stub: append JSON lines to a local file. Task 5 upgrades this to a
Snowflake AUDIT table. Important governance note for Task 5: the audit WRITER
must NOT reuse the read-only agent role. Use a separate least-privilege writer
(INSERT-only on an AUDIT schema) so the query path stays strictly read-only.

The public signature stays stable across both implementations.
"""

from __future__ import annotations
import json
import os
from datetime import datetime, timezone

AUDIT_PATH = os.environ.get("AGENT_AUDIT_LOG", "audit_log.jsonl")


def audit_log(
    *,
    metrics: list[str] | None,
    group_by: list[str] | None,
    team: str,
    status: str,            # 'ok' | 'refused' | 'error'
    detail: str | None,
    row_count: int,
    question: str | None = None,   # NL question — populated once Task 4 lands
) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "team": team,
        "question": question,
        "metrics": metrics,
        "group_by": group_by,
        "status": status,
        "detail": detail,
        "row_count": row_count,
    }
    with open(AUDIT_PATH, "a") as fh:
        fh.write(json.dumps(record) + "\n")