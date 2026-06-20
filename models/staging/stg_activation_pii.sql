-- =============================================================
-- Petal & Co — Staging Layer (Reverse ETL)
-- Model: stg_activation_pii.sql
-- Schema: PETAL_CO_DW.STAGING
-- Description: Generates SYNTHETIC, deterministic activation
--              attributes for the reverse-ETL demo:
--                - a fake, non-deliverable email (@example.com)
--                - a marketing_consent flag (~70% TRUE)
--                - an is_erased flag (~5% TRUE)
--
--              IMPORTANT — GDPR / safety by design:
--              * This model NEVER reads RAW.EMAIL or any real PII.
--                The activation email is fabricated from CUSTOMER_ID
--                on the @example.com reserved sink domain (RFC 2606),
--                so a downstream win-back flow can never reach a real
--                person.
--              * Real email stays SHA-256 hashed in stg_customers and
--                is never un-masked anywhere in the warehouse.
--              * Flags are derived deterministically from CUSTOMER_ID
--                so every run is reproducible (no random()).
-- =============================================================

WITH customers AS (

    SELECT
        CUSTOMER_ID
    FROM {{ ref('stg_customers') }}

),

synthetic AS (

    SELECT
        CUSTOMER_ID,

        -- Synthetic, NON-DELIVERABLE activation email.
        -- @example.com is reserved (RFC 2606) and cannot send.
        'demo+' || CUSTOMER_ID || '@example.com'        AS ACTIVATION_EMAIL,

        -- Deterministic marketing consent (~70% TRUE).
        -- Hash the ID -> stable integer -> modulo bucket.
        -- ABS(HASH()) is stable per-value within Snowflake.
        (ABS(HASH(CUSTOMER_ID)) % 100) < 70             AS MARKETING_CONSENT,

        -- Deterministic erasure flag (~5% TRUE).
        -- Offset the hash so it's independent of the consent bucket.
        (ABS(HASH(CUSTOMER_ID || 'erasure_salt')) % 100) < 5
                                                         AS IS_ERASED

    FROM customers

)

SELECT
    CUSTOMER_ID,
    ACTIVATION_EMAIL,
    MARKETING_CONSENT,
    IS_ERASED
FROM synthetic