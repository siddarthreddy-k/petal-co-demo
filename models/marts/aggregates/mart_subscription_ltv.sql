-- =============================================================
-- Petal & Co — Mart Layer
-- Model: mart_subscription_ltv.sql
-- Schema: PETAL_CO_DW.MARTS
-- Description: Subscription vs one-time customer LTV analysis.
--              Groups customers by acquisition cohort, channel,
--              and customer_type. Tracks cumulative net revenue
--              at 30, 90, 180, and 365 days.
--              Key story: Subscription customers generate 3-4x
--              more revenue over 12 months than one-time buyers.
--              Meta acquires mostly one-time buyers — lowest LTV
--              despite highest spend.
-- =============================================================

WITH customers AS (
    SELECT
        CUSTOMER_ID,
        ACQUISITION_CHANNEL,
        ACQUISITION_DATE,
        ACQUISITION_COHORT,
        CUSTOMER_TYPE,
        IS_SUBSCRIBER,
        CHANNEL_TYPE
    FROM {{ ref('stg_customers') }}
),

orders AS (
    SELECT
        ORDER_ID,
        CUSTOMER_ID,
        ORDER_DATE,
        NET_REVENUE,
        IS_RETURNED,
        ADJUSTED_REVENUE,
        DAYS_SINCE_ACQ,
        IS_SUBSCRIPTION_ORDER
    FROM {{ ref('stg_orders') }}
),

customer_orders AS (
    SELECT
        c.CUSTOMER_ID,
        c.ACQUISITION_CHANNEL,
        c.ACQUISITION_DATE,
        c.ACQUISITION_COHORT,
        c.CUSTOMER_TYPE,
        c.IS_SUBSCRIBER,
        c.CHANNEL_TYPE,
        o.ORDER_DATE,
        o.NET_REVENUE,
        o.ADJUSTED_REVENUE,
        o.IS_RETURNED,
        o.DAYS_SINCE_ACQ,
        o.IS_SUBSCRIPTION_ORDER
    FROM customers c
    LEFT JOIN orders o ON c.CUSTOMER_ID = o.CUSTOMER_ID
),

cohort_ltv AS (
    SELECT
        ACQUISITION_COHORT,
        ACQUISITION_CHANNEL,
        CUSTOMER_TYPE,
        IS_SUBSCRIBER,
        CHANNEL_TYPE,

        -- Cohort size
        COUNT(DISTINCT CUSTOMER_ID)                         AS COHORT_SIZE,

        -- Total orders
        COUNT(ORDER_DATE)                                   AS TOTAL_ORDERS,
        SUM(IS_RETURNED)                                    AS TOTAL_RETURNS,
        SUM(IS_SUBSCRIPTION_ORDER)                          AS SUBSCRIPTION_ORDERS,

        -- Return rate as decimal — format as % in Looker Studio
        ROUND(SUM(IS_RETURNED) / NULLIF(COUNT(ORDER_DATE), 0), 4)
                                                            AS RETURN_RATE,

        -- Orders per customer
        ROUND(COUNT(ORDER_DATE) / NULLIF(COUNT(DISTINCT CUSTOMER_ID), 0), 2)
                                                            AS ORDERS_PER_CUSTOMER,

        -- Cumulative LTV at each interval
        ROUND(SUM(CASE WHEN DAYS_SINCE_ACQ <= 30
            THEN ADJUSTED_REVENUE ELSE 0 END), 2)           AS LTV_30D,

        ROUND(SUM(CASE WHEN DAYS_SINCE_ACQ <= 90
            THEN ADJUSTED_REVENUE ELSE 0 END), 2)           AS LTV_90D,

        ROUND(SUM(CASE WHEN DAYS_SINCE_ACQ <= 180
            THEN ADJUSTED_REVENUE ELSE 0 END), 2)           AS LTV_180D,

        ROUND(SUM(CASE WHEN DAYS_SINCE_ACQ <= 365
            THEN ADJUSTED_REVENUE ELSE 0 END), 2)           AS LTV_365D,

        -- LTV per customer at each interval
        ROUND(SUM(CASE WHEN DAYS_SINCE_ACQ <= 30
            THEN ADJUSTED_REVENUE ELSE 0 END)
            / NULLIF(COUNT(DISTINCT CUSTOMER_ID), 0), 2)   AS LTV_30D_PER_CUSTOMER,

        ROUND(SUM(CASE WHEN DAYS_SINCE_ACQ <= 90
            THEN ADJUSTED_REVENUE ELSE 0 END)
            / NULLIF(COUNT(DISTINCT CUSTOMER_ID), 0), 2)   AS LTV_90D_PER_CUSTOMER,

        ROUND(SUM(CASE WHEN DAYS_SINCE_ACQ <= 180
            THEN ADJUSTED_REVENUE ELSE 0 END)
            / NULLIF(COUNT(DISTINCT CUSTOMER_ID), 0), 2)   AS LTV_180D_PER_CUSTOMER,

        ROUND(SUM(CASE WHEN DAYS_SINCE_ACQ <= 365
            THEN ADJUSTED_REVENUE ELSE 0 END)
            / NULLIF(COUNT(DISTINCT CUSTOMER_ID), 0), 2)   AS LTV_365D_PER_CUSTOMER

    FROM customer_orders
    GROUP BY 1, 2, 3, 4, 5
)

SELECT * FROM cohort_ltv
ORDER BY ACQUISITION_COHORT, ACQUISITION_CHANNEL, CUSTOMER_TYPE