-- =============================================================
-- Petal & Co — Dimensional Layer
-- Model: dim_subscriptions.sql
-- Schema: PETAL_CO_DW.MARTS
-- Description: Subscription dimension table.
--              One row per subscription with lifetime metrics.
-- =============================================================

WITH subscriptions AS (
    SELECT
        SUBSCRIPTION_ID,
        CUSTOMER_ID,
        PRODUCT_CATEGORY,
        PLAN_TYPE,
        START_DATE,
        START_COHORT,
        STATUS,
        CANCELLATION_DATE,
        LIFETIME_DAYS,
        IS_ACTIVE,
        IS_CHURNED,
        ORDER_INTERVAL_DAYS
    FROM {{ ref('stg_subscriptions') }}
)

SELECT
    SUBSCRIPTION_ID,
    CUSTOMER_ID,
    PRODUCT_CATEGORY,
    PLAN_TYPE,
    START_DATE,
    START_COHORT,
    STATUS,
    CANCELLATION_DATE,
    LIFETIME_DAYS,
    IS_ACTIVE,
    IS_CHURNED,
    ORDER_INTERVAL_DAYS
FROM subscriptions