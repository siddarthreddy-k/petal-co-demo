# MCP server + governed analytics agent (P3)

One tool, `query_metric`, over the dbt/MetricFlow semantic layer, running under a
read-only Snowflake role, with a fail-closed boot check, a standalone audit
trail, and the full **governance sandwich** — an input guardrail *and* an output
validator around the query agent.

## Architecture (the governance sandwich)

```
question ─▶ INPUT guardrail ─▶ query agent (one governed tool) ─▶ OUTPUT validator ─▶ user
           (guardrail.py)       (agent.py + server.py)             (output_validator.py)
                          every step is written to the audit trail (audit.py)
```

- **Input guardrail** vets the REQUEST (off-topic / PII-extraction / injection), fail-closed.
- **Query agent** answers via the ONE allowlisted tool — no raw SQL, read-only role, undefined = refused.
- **Output validator** vets the ANSWER against the figures actually queried (ungrounded number / unlabelled advice / PII leak), fail-closed — a bad answer is withheld, not sent.
- **Audit** records every tool call and policy decision, attributable to who asked.

Guarantees: HARD on data (never a number from an unblessed source/join; every query audited), SOFT on advice (grounded, labelled). Row-level customer identity is out by design — enforced at three layers (guardrail, catalog allowlist, output validator).

## Files
- `server.py`         — MCP server; exposes `query_metric`; refuses to boot if the cage is open.
- `agent.py`          — standalone agent loop; runs the guardrail → tool → validator sandwich.
- `guardrail.py`      — INPUT policy agent (fail-closed allow/block).
- `output_validator.py` — OUTPUT policy agent; judges the answer vs the queried evidence (fail-closed).
- `catalog.py`        — fail-closed allowlist, built from the live semantic layer.
- `mf_executor.py`    — runs `mf query` under the RO target; boot cage check.
- `audit.py`          — standalone audit; JSONL always + opt-in Snowflake insert-only writer.
- `sql/audit_setup.sql` — creates the audit table + the SEPARATE insert-only writer role/user.
- `test_executor.py`  — smoke test for the cage + catalog + a real governed query (no MCP client).
- `test_validator.py` — smoke test for the output validator (no warehouse; API key only).
- `slack_bot.py`      — Slack Socket-Mode front door; opt-in thread-reading.

## THE critical detail (do not "fix" this)
`mf query` **ignores `--target`** — it reads **`DBT_TARGET`** from the environment.
Every subprocess here sets `DBT_TARGET=agent_ro`. If you replace that with a
`--target` flag, mf silently runs as your default (SYSADMIN) target, which CAN
read RAW — an invisible cage bypass. The boot check exists to catch exactly that.

## Prereqs
- `agent_ro` target in profiles.yml, service user + RO role, cage proven.
- Churn semantic layer built + validated.
- Run everything from the dbt project root (where profiles.yml lives), in the `(schemaworks)` env.

## Env
```
export ANTHROPIC_API_KEY='sk-ant-...'
export AGENT_RO_KEY_PASSPHRASE='...'   # agent RO key passphrase (profiles.yml reads it)
# optional overrides:
export AGENT_RO_TARGET=agent_ro
export DBT_PROFILES_DIR=.              # defaults to cwd
export AGENT_AUDIT_LOG=./audit_log.jsonl

# Audit -> Snowflake (opt-in; off unless ENABLED=1). See sql/audit_setup.sql.
export AUDIT_SNOWFLAKE_ENABLED=1
export SNOWFLAKE_ACCOUNT='...'
export AUDIT_PRIVATE_KEY_PATH='/abs/path/svc_audit_writer_key.p8'
export AUDIT_KEY_PASSPHRASE='...'      # 3rd key pair, separate from agent RO
# export AUDIT_STRICT=1                # fail-closed audit (refuse rather than answer un-audited)

# Slack (slack_bot.py):
export SLACK_BOT_TOKEN='xoxb-...'
export SLACK_APP_TOKEN='xapp-...'
# export SLACK_READ_THREADS=1          # opt in to thread-reading (see disclosure below)
```

## Test first, then serve
```bash
# 1. Validator (no warehouse; only ANTHROPIC_API_KEY) — expect 6/6:
python mcp_server/test_validator.py

# 2. Cage + catalog + a real governed query (no MCP client):
python mcp_server/test_executor.py
#    expect: cage OK, churn metrics listed, MRR-by-band rows, undefined metric refused

# 3. The agent (CLI), or the MCP server:
pip install -r mcp_server/requirements.txt
python mcp_server/agent.py      # interactive CLI
python mcp_server/server.py     # MCP server
python mcp_server/slack_bot.py  # Slack front door
```

---

# P3 Depth — Build Notes & Local Test Checklist

Four depth items completing the P3 marquee arc. Test locally in the
`(schemaworks)` env from the dbt project root.

## What changed

| File | Change |
|---|---|
| `output_validator.py` | **NEW** — answer-side policy agent (claude-haiku, fail-closed). Completes the governance sandwich. |
| `agent.py` | `ask()` now runs the output validator before returning; collects `evidence` (the rows actually queried) for it; adds optional `context` param (Slack threads) that is **not** sent to the input guardrail; audits `answered` / `blocked_output` with the question. |
| `audit.py` | Dual-write: JSONL (always) **+** Snowflake `QUERY_LOG` (opt-in, insert-only writer, key-pair). Resilient by default; `AUDIT_STRICT=1` for fail-closed audit. |
| `sql/audit_setup.sql` | **NEW** — creates the audit DB/table + the **separate insert-only writer role** + service user. |
| `slack_bot.py` | **NEW** thread-reading, **off by default** (`SLACK_READ_THREADS=1`), with privacy disclosure + per-answer note. |
| `test_validator.py` | **NEW** — isolated smoke test for the validator (no warehouse needed). |
| `requirements.txt` | adds `snowflake-connector-python`, `cryptography` (only used when the Snowflake sink is on). |

Backward-compatible: with `AUDIT_SNOWFLAKE_ENABLED` and `SLACK_READ_THREADS`
unset, behaviour is exactly as before **plus** the output validator.

## Item 1 — Output validator (the marquee)

**A. Isolated test (no warehouse, just ANTHROPIC_API_KEY):**
```
python mcp_server/test_validator.py
```
Expect **6/6 as expected**: grounded fact ALLOW, ungrounded number BLOCK, unlabelled
advice BLOCK, grounded+labelled advice ALLOW, PII leak BLOCK, safe refusal ALLOW.
If any miss, tune `_POLICY` in `output_validator.py` (same way the input guardrail
was tuned) and re-run.

**B. Live, end-to-end (warehouse up, agent running):**
```
python mcp_server/agent.py
```
- Golden questions still answer correctly and now print `[validator] ALLOW`:
  - `how many high-risk for churn?` → **276**
  - `what's at-risk MRR?` → **£4,930**
- Provoke a block: ask something that tempts a made-up figure, e.g.
  `what was our welcome-offer conversion rate last quarter?` — the agent should
  refuse (no such metric); if a number ever slips through, the validator prints
  `[validator] BLOCK (UNGROUNDED_NUMBER)` and the answer is withheld.
- `audit_log.jsonl` now has `status:"answered"` (with the `question`) on good
  answers and `status:"blocked_output"` on withheld ones.

## Item 2 — Audit → Snowflake table

**Setup (once):**
1. Generate the **3rd** key pair (never reuse the agent-RO or Hightouch keys):
   ```
   openssl genrsa 2048 | openssl pkcs8 -topk8 -v2 aes-256-cbc -inform PEM -out svc_audit_writer_key.p8
   openssl rsa -in svc_audit_writer_key.p8 -pubout -out svc_audit_writer_key.pub
   ```
2. Run `mcp_server/sql/audit_setup.sql` in Snowsight, pasting the public-key body
   into the `ALTER USER ... SET RSA_PUBLIC_KEY` line.
3. Add to `.env` (all read from env, nothing hard-coded):
   ```
   AUDIT_SNOWFLAKE_ENABLED=1
   SNOWFLAKE_ACCOUNT=<account>
   AUDIT_PRIVATE_KEY_PATH=<abs path to svc_audit_writer_key.p8>
   AUDIT_KEY_PASSPHRASE=<shell-safe passphrase>
   ```

**Prove the write:** run a question, then (as SYSADMIN, which has SELECT):
```
SELECT ts, team, question, status, row_count
FROM SCHEMA_WORKS_AUDIT.LOGS.QUERY_LOG ORDER BY ts DESC LIMIT 10;
```
Metrics/`group_by` are `VARIANT` — query with `metrics[0]::string` etc.

**Prove the isolation (the governance point):**
- As `SCHEMA_WORKS_AUDIT_WRITER`: `INSERT ... SELECT ...` succeeds, `SELECT * FROM ... QUERY_LOG` **fails** (no SELECT). Snippet at the bottom of the SQL file.
- As `SCHEMA_WORKS_AGENT_RO` (the agent's role): it has **no** INSERT on the audit table — the query path stays strictly read-only.
- Confirm the audit writer has **no** access to `PETAL_CO_DW` marts/RAW.

**Resilience check:** stop the warehouse / use a bad key → the agent still answers
and still writes JSONL; stderr shows one `Snowflake audit write failed` line.
Set `AUDIT_STRICT=1` only if you want the agent to refuse rather than answer
un-audited.

## Item 3 — customer_id / top-N (decision: row-level OUT by design)

No code toggle added — the policy is enforced at three layers now:
1. input guardrail blocks `PII_EXTRACTION`;
2. catalog allowlist has no `customer` entity → `group_by customer` is refused;
3. output validator blocks any answer containing an id/name/email (`PII_LEAK`).

**Verify:** `who are the ten most likely to churn?` → still **refuses**, offers
aggregates. This is the signature demo — confirm it survives the new pipeline.

## Item 4 — Slack thread-reading (opt-in, disclosed)

**Off by default** — no scope or behaviour change unless you opt in.

To enable:
1. In api.slack.com → OAuth & Permissions add `channels:history` (and
   `groups:history` / `mpim:history` if used there); **reinstall** the app.
2. `set SLACK_READ_THREADS=1` in the terminal, then `python mcp_server/slack_bot.py`.
   Startup prints a reminder that thread messages now go to the Anthropic API.

**Test:** in a thread with a few messages, `@mention` the bot with a question that
only makes sense with the thread → it answers using the context and appends the
"I read this thread" note. With the flag off, it sees only the tagging message
(as before). The input guardrail still vets your actual question, not the chatter.

> Privacy: enabling this sends other people's messages to the Anthropic API.
> Disclose it to anyone in those channels before turning it on.

## Before any external claim
- Re-verify counts against the **live** semantic layer: `mf list metrics`,
  `mf list dimensions --metrics <names>`. The Metric Dictionary PDF must match.
- Numbers of record: churn **High 276 / Med 581 / Low 1,054**;
  `at_risk_mrr` **£4,930.87** (High £26 live, Medium £4,904); total scored MRR ≈ £10,636.

## Ops reminders
- **One process only.** After editing, kill stray `python.exe`
  (`tasklist | findstr python`) so a zombie Socket-Mode bot isn't holding the
  WebSocket on stale code. Verify with `findstr "def ask" mcp_server\agent.py`.
- **Rotate the leaked secrets** at this cut-point: both Slack tokens + the agent-key
  passphrase (shell-safe: no `%^#`, spaces, quotes). Adding the audit key pair is
  the natural moment. Confirm `.gitignore` covers `.env`, `*.p8`, `*.pub`,
  `audit_log.jsonl`, `__pycache__/`.

---

## Status (was "not here yet")
- [x] LLM connection / agent loop — `agent.py` (CLI) + `slack_bot.py` (Slack).
- [x] Input guardrail — `guardrail.py`.
- [x] **Output validator** — `output_validator.py` (governance sandwich complete).
- [x] **Audit → Snowflake AUDIT table** — `audit.py` + `sql/audit_setup.sql` (separate insert-only writer).
- [x] **Slack thread-reading** — `slack_bot.py` (opt-in, disclosed).
- [ ] Team-context ENFORCEMENT (`team_context` is recorded, not yet gated per team).
- [ ] Router / domain-specialist agents (the later "wow" arc).
- [ ] RAG-for-catalog (when metric count outgrows the prompt).