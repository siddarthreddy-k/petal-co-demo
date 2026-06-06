-- =============================================================
-- Petal & Co — Dimensional Layer
-- Model: dim_customers.sql
-- Schema: PETAL_CO_DW.MARTS
-- Description: Customer dimension table.
--              PII fields remain hashed from staging layer.
--              GDPR compliant — no raw email or name exposed.
-- =============================================================

WITH customers AS (
    SELECT
        CUSTOMER_ID,
        EMAIL_HASH,
        FIRST_NAME_HASH,
        ACQUISITION_CHANNEL,
        ACQUISITION_DATE,
        ACQUISITION_COHORT,
        ACQUISITION_QUARTER,
        COUNTRY,
        CUSTOMER_TYPE,
        IS_SUBSCRIBER,
        EMAIL_SUBSCRIBED,
        CHANNEL_TYPE,
        REGION
    FROM {{ ref('stg_customers') }}
)

SELECT
    CUSTOMER_ID,
    EMAIL_HASH,
    FIRST_NAME_HASH,
    ACQUISITION_CHANNEL,
    ACQUISITION_DATE,
    ACQUISITION_COHORT,
    ACQUISITION_QUARTER,
    COUNTRY,
    REGION,
    CUSTOMER_TYPE,
    IS_SUBSCRIBER,
    EMAIL_SUBSCRIBED,
    CHANNEL_TYPE
FROM customers