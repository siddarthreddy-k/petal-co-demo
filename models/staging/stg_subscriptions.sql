-- =============================================================
-- Petal & Co — Staging Layer
-- Model: stg_subscriptions.sql
-- Schema: PETAL_CO_DW.STAGING
-- Description: Cleans RAW.SUBSCRIPTIONS and adds derived fields
--              for subscription lifetime and churn analysis.
-- =============================================================

WITH base AS (
    SELECT
        SUBSCRIPTION_ID,
        CUSTOMER_ID,
        LOWER(TRIM(PRODUCT_CATEGORY))           AS PRODUCT_CATEGORY,
        LOWER(TRIM(PLAN_TYPE))                  AS PLAN_TYPE,
        TRY_TO_DATE(START_DATE)                 AS START_DATE,
        LOWER(TRIM(STATUS))                     AS STATUS,
        TRY_TO_DATE(CANCELLATION_DATE)          AS CANCELLATION_DATE,
        LOADED_AT
    FROM {{ source('raw', 'subscriptions') }}
    WHERE SUBSCRIPTION_ID IS NOT NULL
),

enriched AS (
    SELECT
        SUBSCRIPTION_ID,
        CUSTOMER_ID,
        PRODUCT_CATEGORY,
        PLAN_TYPE,
        START_DATE,
        STATUS,
        CANCELLATION_DATE,
        LOADED_AT,

        -- Subscription lifetime in days
        CASE
            WHEN STATUS = 'cancelled' AND CANCELLATION_DATE IS NOT NULL
            THEN DATEDIFF('day', START_DATE, CANCELLATION_DATE)
            ELSE DATEDIFF('day', START_DATE, CURRENT_DATE())
        END                                     AS LIFETIME_DAYS,

        -- Is the subscription still active
        CASE
            WHEN STATUS = 'active' THEN TRUE
            ELSE FALSE
        END                                     AS IS_ACTIVE,

        -- Churn flag
        CASE
            WHEN STATUS = 'cancelled' THEN TRUE
            ELSE FALSE
        END                                     AS IS_CHURNED,

        -- Order interval in days based on plan type
        CASE
            WHEN PLAN_TYPE = 'monthly'   THEN 30
            WHEN PLAN_TYPE = 'quarterly' THEN 90
            ELSE NULL
        END                                     AS ORDER_INTERVAL_DAYS,

        -- Cohort month
        DATE_TRUNC('month', START_DATE)         AS START_COHORT

    FROM base
)

SELECT * FROM enriched