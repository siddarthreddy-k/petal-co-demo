# MCP server — governed query tool (Robust CLI)

One tool, `query_metric`, over the dbt/MetricFlow semantic layer, running under
the Task 4 read-only Snowflake role, with a fail-closed boot check and
standalone audit.

## Files
- `server.py`      — MCP server; exposes `query_metric`; refuses to boot if the cage is open.
- `catalog.py`     — fail-closed allowlist, built from the live semantic layer (Task 6).
- `mf_executor.py` — runs `mf query` under the RO target; boot cage check (Task 7).
- `audit.py`       — standalone audit module (W1 stub → Snowflake in a later task).
- `test_executor.py` — smoke test for Tasks 6+7, no MCP client needed.

## THE critical detail (do not "fix" this)
`mf query` **ignores `--target`** — it reads **`DBT_TARGET`** from the environment.
Every subprocess here sets `DBT_TARGET=agent_ro`. If you replace that with a
`--target` flag, mf silently runs as your default (SYSADMIN) target, which CAN
read RAW — an invisible cage bypass. The boot check exists to catch exactly that.

## Prereqs
- `agent_ro` target in profiles.yml, service user + RO role, cage proven.
- Churn semantic layer built + validated.
- Run everything from the dbt project root (where profiles.yml lives), in the `(dbt)` env.

## Env
```
export AGENT_RO_KEY_PASSPHRASE='...'   # agent key passphrase (profiles.yml reads it)
# optional overrides:
export AGENT_RO_TARGET=agent_ro
export DBT_PROFILES_DIR=.              # defaults to cwd
export AGENT_AUDIT_LOG=./audit_log.jsonl
```

## Test first, then serve
```bash
# 1. Smoke-test the plumbing (no MCP client):
python mcp_server/test_executor.py
#    expect: cage OK, churn metrics listed, MRR-by-band rows, undefined metric refused

# 2. Then run the MCP server:
pip install -r mcp_server/requirements.txt
python mcp_server/server.py
```

## Not here yet (later arc)
- LLM connection / MCP client wiring.
- Audit → Snowflake AUDIT table (with a SEPARATE insert-only writer role, never the RO agent role).
- Team-context enforcement (`team_context` is recorded, not gated).
- Guardrail/validator agent (the multi-agent arc).