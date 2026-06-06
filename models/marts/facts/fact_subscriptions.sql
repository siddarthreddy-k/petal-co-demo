-- =============================================================
-- Petal & Co — Fact Layer
-- Model: fct_subscriptions.sql
-- Schema: PETAL_CO_DW.MARTS
-- Description: Subscription fact table.
--              One row per subscription with lifetime metrics
--              and foreign keys to dimension tables.
--              Used for churn analysis and MRR tracking.
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
),

orders AS (
    SELECT
        SUBSCRIPTION_ID,
        COUNT(ORDER_ID)                         AS TOTAL_ORDERS,
        SUM(GROSS_REVENUE)                      AS TOTAL_GROSS_REVENUE,
        SUM(NET_REVENUE)                        AS TOTAL_NET_REVENUE,
        SUM(ADJUSTED_REVENUE)                   AS TOTAL_ADJUSTED_REVENUE,
        SUM(DISCOUNT)                           AS TOTAL_DISCOUNTS,
        SUM(IS_RETURNED)                        AS TOTAL_RETURNS,
        MIN(ORDER_DATE)                         AS FIRST_ORDER_DATE,
        MAX(ORDER_DATE)                         AS LAST_ORDER_DATE
    FROM {{ ref('stg_orders') }}
    WHERE SUBSCRIPTION_ID IS NOT NULL
    GROUP BY 1
)

SELECT
    -- Keys
    s.SUBSCRIPTION_ID,
    s.CUSTOMER_ID,
    s.PRODUCT_CATEGORY                      AS PRODUCT_CATEGORY_KEY,
    s.PLAN_TYPE,

    -- Dates
    s.START_DATE,
    s.START_COHORT,
    s.CANCELLATION_DATE,
    o.FIRST_ORDER_DATE,
    o.LAST_ORDER_DATE,

    -- Status
    s.STATUS,
    s.IS_ACTIVE,
    s.IS_CHURNED,
    s.LIFETIME_DAYS,
    s.ORDER_INTERVAL_DAYS,

    -- Order metrics
    COALESCE(o.TOTAL_ORDERS, 0)             AS TOTAL_ORDERS,
    COALESCE(o.TOTAL_RETURNS, 0)            AS TOTAL_RETURNS,
    COALESCE(o.TOTAL_GROSS_REVENUE, 0)      AS TOTAL_GROSS_REVENUE,
    COALESCE(o.TOTAL_NET_REVENUE, 0)        AS TOTAL_NET_REVENUE,
    COALESCE(o.TOTAL_ADJUSTED_REVENUE, 0)   AS TOTAL_ADJUSTED_REVENUE,
    COALESCE(o.TOTAL_DISCOUNTS, 0)          AS TOTAL_DISCOUNTS,

    -- Derived
    CASE
        WHEN COALESCE(o.TOTAL_ORDERS, 0) > 0
        THEN ROUND(o.TOTAL_NET_REVENUE / o.TOTAL_ORDERS, 2)
        ELSE 0
    END                                     AS AVG_ORDER_VALUE,

    CASE
        WHEN COALESCE(o.TOTAL_ORDERS, 0) > 0
        THEN ROUND(o.TOTAL_RETURNS / o.TOTAL_ORDERS, 4)
        ELSE 0
    END                                     AS RETURN_RATE,

    -- Monthly recurring revenue estimate
    CASE
        WHEN s.IS_ACTIVE AND s.ORDER_INTERVAL_DAYS > 0
        THEN ROUND(
            COALESCE(o.TOTAL_NET_REVENUE, 0)
            / NULLIF(s.LIFETIME_DAYS, 0) * 30, 2)
        ELSE 0
    END                                     AS ESTIMATED_MRR

FROM subscriptions s
LEFT JOIN orders o ON s.SUBSCRIPTION_ID = o.SUBSCRIPTION_ID