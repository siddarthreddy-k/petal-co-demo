------------------------------------------------------------------------------
-- P3 · Task 7 — Audit trail in Snowflake (insert-only writer)
--
-- Promotes the JSONL audit stub to a warehouse-native table so "every query is
-- logged and attributable" becomes QUERYABLE (the agent can even answer
-- questions about its own usage — via the READ-ONLY role, never this one).
--
-- GOVERNANCE SPINE (do not collapse these into one role):
--   * SCHEMA_WORKS_AGENT_RO   — the agent's query path. READ-ONLY on marts.
--                               It must NEVER get INSERT on the audit table.
--   * SCHEMA_WORKS_AUDIT_WRITER (this script) — a SEPARATE least-privilege role
--                               that can ONLY INSERT audit rows. No SELECT on
--                               anything, no access to marts or RAW.
--   A human/admin role reads the audit table. The writer cannot read its own
--   trail; the agent-RO role cannot write it. Neither can tamper with the other.
--
-- 3rd KEY PAIR (one per service identity — agent RO, Hightouch RO, and now this
-- audit writer). Generate BEFORE running this script:
--
--   openssl genrsa 2048 | openssl pkcs8 -topk8 -v2 aes-256-cbc \
--       -inform PEM -out svc_audit_writer_key.p8
--   openssl rsa -in svc_audit_writer_key.p8 -pubout -out svc_audit_writer_key.pub
--   # strip the header/footer + newlines from the .pub for the RSA_PUBLIC_KEY value
--
-- Store svc_audit_writer_key.p8 next to your other service keys (gitignored:
-- *.p8, *.pub). Its passphrase becomes AUDIT_KEY_PASSPHRASE in .env.
------------------------------------------------------------------------------

-- =====================================================================
-- 1. Database + schema + table  (run as SYSADMIN)
-- =====================================================================
USE ROLE SYSADMIN;

CREATE DATABASE IF NOT EXISTS SCHEMA_WORKS_AUDIT;
CREATE SCHEMA   IF NOT EXISTS SCHEMA_WORKS_AUDIT.LOGS;

CREATE TABLE IF NOT EXISTS SCHEMA_WORKS_AUDIT.LOGS.QUERY_LOG (
    ts          TIMESTAMP_TZ   NOT NULL,   -- when the event happened (UTC)
    team        STRING,                    -- team_context: 'cli' | 'slack:<user>' | ...
    question    STRING,                    -- the natural-language question asked
    metrics     VARIANT,                   -- JSON array of requested metric names
    group_by    VARIANT,                   -- JSON array of requested dimensions
    status      STRING,                    -- ok|refused|error|blocked|blocked_output|answered
    detail      STRING,                    -- refusal/error/policy reason (nullable)
    row_count   NUMBER,                    -- rows the governed query returned
    load_ts     TIMESTAMP_TZ   DEFAULT CURRENT_TIMESTAMP()  -- server-side insert time
);

-- =====================================================================
-- 2. Insert-only writer role  (run as SECURITYADMIN or ACCOUNTADMIN)
-- =====================================================================
USE ROLE SECURITYADMIN;

CREATE ROLE IF NOT EXISTS SCHEMA_WORKS_AUDIT_WRITER;

-- Warehouse to run the INSERT (DML needs a running warehouse). Reuse the small
-- existing compute; USAGE on a warehouse is not a data-access grant.
GRANT USAGE ON WAREHOUSE COMPUTE_WH        TO ROLE SCHEMA_WORKS_AUDIT_WRITER;

-- See the database + schema, and INSERT into the one table. NOTHING else.
GRANT USAGE  ON DATABASE SCHEMA_WORKS_AUDIT               TO ROLE SCHEMA_WORKS_AUDIT_WRITER;
GRANT USAGE  ON SCHEMA   SCHEMA_WORKS_AUDIT.LOGS          TO ROLE SCHEMA_WORKS_AUDIT_WRITER;
GRANT INSERT ON TABLE    SCHEMA_WORKS_AUDIT.LOGS.QUERY_LOG TO ROLE SCHEMA_WORKS_AUDIT_WRITER;
-- NOTE: deliberately NO SELECT. The writer cannot read the trail it writes.
-- NOTE: deliberately NO grant to SCHEMA_WORKS_AGENT_RO here — the query path
--       stays strictly read-only and cannot touch the audit table.

-- =====================================================================
-- 3. Service user for the writer, key-pair auth  (run as SECURITYADMIN)
-- =====================================================================
CREATE USER IF NOT EXISTS SVC_SCHEMA_WORKS_AUDIT
    DEFAULT_ROLE      = SCHEMA_WORKS_AUDIT_WRITER
    DEFAULT_WAREHOUSE = COMPUTE_WH
    COMMENT           = 'Insert-only audit writer for the P3 governed agent. Key-pair auth.';

-- Paste the single-line public key body (no BEGIN/END lines, no newlines):
ALTER USER SVC_SCHEMA_WORKS_AUDIT SET RSA_PUBLIC_KEY = '<PASTE_PUBLIC_KEY_BODY_HERE>';

GRANT ROLE SCHEMA_WORKS_AUDIT_WRITER TO USER SVC_SCHEMA_WORKS_AUDIT;

-- =====================================================================
-- 4. Reader grant for a human/admin  (run as SECURITYADMIN)
-- =====================================================================
-- Someone authorised must be able to READ the trail (the writer cannot).
-- Grant SELECT to whichever role you query Snowflake with day-to-day.
GRANT USAGE  ON DATABASE SCHEMA_WORKS_AUDIT               TO ROLE SYSADMIN;
GRANT USAGE  ON SCHEMA   SCHEMA_WORKS_AUDIT.LOGS          TO ROLE SYSADMIN;
GRANT SELECT ON TABLE    SCHEMA_WORKS_AUDIT.LOGS.QUERY_LOG TO ROLE SYSADMIN;

-- Optional: let the READ-ONLY agent role SELECT the audit table too, so the
-- agent can answer "how many questions did I refuse today?" through its normal
-- read-only path. This grants SELECT ONLY — never INSERT — so it does not break
-- the separation. Uncomment if you want that demo:
-- GRANT USAGE  ON DATABASE SCHEMA_WORKS_AUDIT               TO ROLE SCHEMA_WORKS_AGENT_RO;
-- GRANT USAGE  ON SCHEMA   SCHEMA_WORKS_AUDIT.LOGS          TO ROLE SCHEMA_WORKS_AGENT_RO;
-- GRANT SELECT ON TABLE    SCHEMA_WORKS_AUDIT.LOGS.QUERY_LOG TO ROLE SCHEMA_WORKS_AGENT_RO;

-- =====================================================================
-- 5. Verify the cage (run these as a check)
-- =====================================================================
-- As the writer, INSERT must work and SELECT must FAIL:
--   USE ROLE SCHEMA_WORKS_AUDIT_WRITER;
--   INSERT INTO SCHEMA_WORKS_AUDIT.LOGS.QUERY_LOG (ts, team, status, row_count)
--       SELECT CURRENT_TIMESTAMP(), 'setup-test', 'ok', 0;      -- should succeed
--   SELECT * FROM SCHEMA_WORKS_AUDIT.LOGS.QUERY_LOG;            -- should FAIL: no SELECT