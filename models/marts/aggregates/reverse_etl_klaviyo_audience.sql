-- =============================================================
-- Petal & Co — Marts Layer (Reverse ETL)
-- Model: reverse_etl_klaviyo_audience.sql
-- Schema: PETAL_CO_DW.MARTS
-- Materialization: view  (always reflects latest scores/consent)
-- Description: The consent-gated activation audience synced to
--              Klaviyo by Hightouch. This is the ONLY object the
--              reverse-ETL read-only role can see.
--
--              GDPR / Security by design (CTO rule):
--              * CONSENT GATE   — only MARKETING_CONSENT = TRUE rows
--              * ERASURE GATE   — IS_ERASED = TRUE rows are excluded
--              * ACTIVE ONLY    — only IS_CHURNED = FALSE (don't win-back
--                                 people who already left; act before churn)
--              * MINIMIZATION   — only the fields Klaviyo needs:
--                                 email + risk_band + churn_prob + driver.
--                                 No hashes, no cohort, no raw PII.
--              * SYNTHETIC PII  — EMAIL is fabricated & non-deliverable
--                                 (see stg_activation_pii).
--
--              Source note: ML_CHURN_RISK_SCORES is written to
--              PETAL_CO_DW.ML by churn_prediction_model.py (Python,
--              outside dbt) -> referenced as a dbt SOURCE, not ref().
-- =============================================================

{{ config(materialized='view') }}

WITH scores AS (

    SELECT
        CUSTOMER_ID,
        CHURN_PROBABILITY,
        RISK_BAND_LABEL          AS RISK_BAND,      -- text: Low/Medium/High
        TOP_CHURN_DRIVER,
        ESTIMATED_MRR,
        IS_CHURNED
    FROM {{ source('ml', 'ML_CHURN_RISK_SCORES') }}

),

activation AS (

    SELECT
        CUSTOMER_ID,
        ACTIVATION_EMAIL,
        MARKETING_CONSENT,
        IS_ERASED
    FROM {{ ref('stg_activation_pii') }}

)

SELECT
    a.ACTIVATION_EMAIL              AS EMAIL,             -- Klaviyo identifier
    s.RISK_BAND                     AS RISK_BAND,
    ROUND(s.CHURN_PROBABILITY, 4)   AS CHURN_PROBABILITY,
    s.TOP_CHURN_DRIVER              AS TOP_CHURN_DRIVER,
    ROUND(s.ESTIMATED_MRR, 2)       AS ESTIMATED_MRR      -- for finance framing

FROM scores s
INNER JOIN activation a
    ON s.CUSTOMER_ID = a.CUSTOMER_ID

-- === THE GATES ===
WHERE a.MARKETING_CONSENT = TRUE      -- consent gate
  AND a.IS_ERASED        = FALSE      -- erasure gate
  AND s.IS_CHURNED       = FALSE      -- active subscribers only