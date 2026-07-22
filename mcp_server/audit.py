"""
Standalone audit module (principle 5).

Kept SEPARATE from the agent so the trail stays complete across channels
(CLI, Slack, future UI) and a future agent can share it. Every tool call and
every policy decision — success, refusal, block, or error — writes one row.

Two sinks, same public signature:

  1. JSONL (always on) — append one JSON line locally. Durable, dependency-free,
     never able to break the agent. This is the fallback of record.

  2. Snowflake AUDIT table (opt-in) — INSERT one row via a SEPARATE, least-
     privilege, INSERT-ONLY writer identity (SVC_SCHEMA_WORKS_AUDIT /
     SCHEMA_WORKS_AUDIT_WRITER, key-pair auth). NEVER the read-only agent role.
     Turn on with AUDIT_SNOWFLAKE_ENABLED=1 once sql/audit_setup.sql has run.

Governance note (why two roles): the query path is read-only and must not be
able to write; the audit writer can only INSERT and cannot read. Neither role
can tamper with the other's domain. See sql/audit_setup.sql.

Resilience: by default a Snowflake write failure is swallowed (logged once to
stderr) so a warehouse hiccup can never kill the Slack Socket-Mode bot — the
JSONL line is still written. Set AUDIT_STRICT=1 to make audit fail-closed
(re-raise on Snowflake write failure) if you'd rather refuse to answer than
answer un-audited.
"""

from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone

AUDIT_PATH = os.environ.get("AGENT_AUDIT_LOG", "audit_log.jsonl")


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in {"1", "true", "yes", "on"}


SNOWFLAKE_ENABLED = _truthy(os.environ.get("AUDIT_SNOWFLAKE_ENABLED"))
STRICT = _truthy(os.environ.get("AUDIT_STRICT"))

# Cached Snowflake connection (built lazily on first successful use).
_conn = None
_warned = False   # so we complain at most once when Snowflake writes fail


def _warn_once(msg: str) -> None:
    global _warned
    if not _warned:
        print(f"[audit] {msg}", file=sys.stderr)
        _warned = True


def _load_private_key(path: str, passphrase: str | None) -> bytes:
    """Load a PKCS#8 private key and return DER bytes for the Snowflake driver."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend

    with open(path, "rb") as fh:
        pkey = serialization.load_pem_private_key(
            fh.read(),
            password=passphrase.encode() if passphrase else None,
            backend=default_backend(),
        )
    return pkey.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _get_connection():
    """Build (once) a key-pair Snowflake connection for the INSERT-ONLY writer.

    Raises on misconfiguration — callers decide whether that's fatal (STRICT) or
    swallowed. Imports are lazy so environments without the writer configured
    (or without snowflake-connector-python installed) still import this module.
    """
    global _conn
    if _conn is not None:
        return _conn

    import snowflake.connector  # lazy

    account = os.environ["SNOWFLAKE_ACCOUNT"]
    key_path = os.environ["AUDIT_PRIVATE_KEY_PATH"]
    passphrase = os.environ.get("AUDIT_KEY_PASSPHRASE")

    _conn = snowflake.connector.connect(
        account=account,
        user=os.environ.get("AUDIT_SNOWFLAKE_USER", "SVC_SCHEMA_WORKS_AUDIT"),
        role=os.environ.get("AUDIT_SNOWFLAKE_ROLE", "SCHEMA_WORKS_AUDIT_WRITER"),
        warehouse=os.environ.get("AUDIT_SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        database=os.environ.get("AUDIT_SNOWFLAKE_DATABASE", "SCHEMA_WORKS_AUDIT"),
        schema=os.environ.get("AUDIT_SNOWFLAKE_SCHEMA", "LOGS"),
        private_key=_load_private_key(key_path, passphrase),
        client_session_keep_alive=True,
    )
    return _conn


_INSERT_SQL = (
    "INSERT INTO {db}.{schema}.QUERY_LOG "
    "(ts, team, question, metrics, group_by, status, detail, row_count) "
    "SELECT %s, %s, %s, PARSE_JSON(%s), PARSE_JSON(%s), %s, %s, %s"
)


def _write_snowflake(record: dict) -> None:
    """INSERT one audit row via the writer identity. May raise; caller handles."""
    global _conn
    db = os.environ.get("AUDIT_SNOWFLAKE_DATABASE", "SCHEMA_WORKS_AUDIT")
    schema = os.environ.get("AUDIT_SNOWFLAKE_SCHEMA", "LOGS")
    sql = _INSERT_SQL.format(db=db, schema=schema)
    params = (
        record["ts"],
        record["team"],
        record["question"],
        json.dumps(record["metrics"]),
        json.dumps(record["group_by"]),
        record["status"],
        record["detail"],
        record["row_count"],
    )
    try:
        conn = _get_connection()
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
        finally:
            cur.close()
    except Exception:
        # Drop a possibly-stale connection so the next call reconnects cleanly.
        try:
            if _conn is not None:
                _conn.close()
        except Exception:
            pass
        _conn = None
        raise


def audit_log(
    *,
    metrics: list[str] | None,
    group_by: list[str] | None,
    team: str,
    status: str,            # ok | refused | error | blocked | blocked_output | answered
    detail: str | None,
    row_count: int,
    question: str | None = None,   # NL question that triggered the event
) -> None:
    record = {
        "ts": datetime.now(timezone.utc),
        "team": team,
        "question": question,
        "metrics": metrics,
        "group_by": group_by,
        "status": status,
        "detail": detail,
        "row_count": row_count,
    }

    # --- Sink 1: JSONL, always, never fatal ------------------------------
    try:
        line = dict(record)
        line["ts"] = record["ts"].isoformat()
        with open(AUDIT_PATH, "a") as fh:
            fh.write(json.dumps(line) + "\n")
    except Exception as e:                       # noqa: BLE001
        _warn_once(f"JSONL audit write failed: {e}")

    # --- Sink 2: Snowflake, opt-in -------------------------------------
    if SNOWFLAKE_ENABLED:
        try:
            _write_snowflake(record)
        except Exception as e:                   # noqa: BLE001
            if STRICT:
                # Fail-closed audit: refuse to proceed un-audited.
                raise
            _warn_once(f"Snowflake audit write failed (continuing on JSONL): {e}")