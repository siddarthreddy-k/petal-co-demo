-- =============================================================
-- Petal & Co — Staging Layer
-- Model: stg_customers.sql
-- Schema: PETAL_CO_DW.STAGING
-- Description: Cleans RAW.CUSTOMERS and applies GDPR-compliant
--              PII handling. Email and first_name are hashed
--              using SHA-256 at this layer and never exposed
--              in marts or dashboards.
--              Compliant with GDPR Article 25 — Privacy by Design.
-- =============================================================

WITH base AS (
    SELECT
        CUSTOMER_ID,
        EMAIL,
        FIRST_NAME,
        LOWER(TRIM(ACQUISITION_CHANNEL))        AS ACQUISITION_CHANNEL,
        TRY_TO_DATE(ACQUISITION_DATE)           AS ACQUISITION_DATE,
        UPPER(TRIM(COUNTRY))                    AS COUNTRY,
        LOWER(TRIM(CUSTOMER_TYPE))              AS CUSTOMER_TYPE,
        EMAIL_SUBSCRIBED,
        LOADED_AT
    FROM {{ source('raw', 'customers') }}
    WHERE CUSTOMER_ID IS NOT NULL
),

gdpr_hashed AS (
    SELECT
        CUSTOMER_ID,

        -- GDPR Article 25 — Privacy by Design
        -- PII fields hashed at staging layer using SHA-256
        -- Raw email and first_name never exposed downstream
        SHA2(LOWER(TRIM(EMAIL)), 256)           AS EMAIL_HASH,
        SHA2(LOWER(TRIM(FIRST_NAME)), 256)      AS FIRST_NAME_HASH,

        ACQUISITION_CHANNEL,
        ACQUISITION_DATE,
        COUNTRY,
        CUSTOMER_TYPE,
        EMAIL_SUBSCRIBED,
        LOADED_AT,

        -- Cohort key — month of acquisition
        DATE_TRUNC('month', ACQUISITION_DATE)   AS ACQUISITION_COHORT,

        -- Quarter of acquisition
        DATE_TRUNC('quarter', ACQUISITION_DATE) AS ACQUISITION_QUARTER,

        -- Channel grouping
        CASE
            WHEN ACQUISITION_CHANNEL IN ('meta', 'google', 'tiktok') THEN 'paid'
            WHEN ACQUISITION_CHANNEL IN ('organic', 'email', 'referral') THEN 'organic'
            ELSE 'unknown'
        END                                     AS CHANNEL_TYPE,

        -- Region grouping
        CASE
            WHEN COUNTRY IN ('GB', 'DE', 'FR', 'NL') THEN 'Europe'
            WHEN COUNTRY IN ('US', 'CA')              THEN 'North America'
            WHEN COUNTRY = 'AU'                       THEN 'APAC'
            ELSE 'Other'
        END                                     AS REGION,

        -- Subscriber flag
        IFF(CUSTOMER_TYPE = 'subscription', 1, 0)::INTEGER  AS IS_SUBSCRIBER

    FROM base
)

SELECT * FROM gdpr_hashed