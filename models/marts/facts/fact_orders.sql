-- =============================================================
-- Petal & Co — Fact Layer
-- Model: fct_orders.sql
-- Schema: PETAL_CO_DW.MARTS
-- Description: Order fact table.
--              One row per order with revenue metrics and
--              foreign keys to all dimension tables.
--              BI tool connects dims to this fact at query time.
-- =============================================================

WITH orders AS (
    SELECT
        ORDER_ID,
        CUSTOMER_ID,
        SUBSCRIPTION_ID,
        ORDER_DATE,
        ORDER_WEEK,
        ORDER_MONTH,
        ORDER_QUARTER,
        ORDER_YEAR,
        PRODUCT_CATEGORY,
        COUNTRY,
        REGION,
        CHANNEL,
        CHANNEL_TYPE,
        CUSTOMER_TYPE,
        IS_SUBSCRIBER,
        GROSS_REVENUE,
        DISCOUNT,
        NET_REVENUE,
        ADJUSTED_REVENUE,
        IS_RETURNED,
        IS_DISCOUNTED,
        IS_SUBSCRIPTION_ORDER,
        DAYS_SINCE_ACQ,
        STATUS
    FROM {{ ref('stg_orders') }}
)

SELECT
    -- Keys
    ORDER_ID,
    CUSTOMER_ID,
    SUBSCRIPTION_ID,
    ORDER_DATE,
    PRODUCT_CATEGORY                        AS PRODUCT_CATEGORY_KEY,

    -- Date parts for slicing
    ORDER_WEEK,
    ORDER_MONTH,
    ORDER_QUARTER,
    ORDER_YEAR,

    -- Attributes
    COUNTRY,
    REGION,
    CHANNEL,
    CHANNEL_TYPE,
    CUSTOMER_TYPE,
    IS_SUBSCRIBER,
    IS_SUBSCRIPTION_ORDER,
    IS_RETURNED,
    IS_DISCOUNTED,
    STATUS,
    DAYS_SINCE_ACQ,

    -- Revenue measures
    GROSS_REVENUE,
    DISCOUNT,
    NET_REVENUE,
    ADJUSTED_REVENUE,

    -- Derived measures
    CASE WHEN IS_RETURNED = 1
         THEN GROSS_REVENUE ELSE 0
    END                                     AS RETURNED_REVENUE,

    GROSS_REVENUE - NET_REVENUE             AS REVENUE_EROSION

FROM orders