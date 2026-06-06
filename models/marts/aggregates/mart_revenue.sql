-- =============================================================
-- Petal & Co — Mart Layer
-- Model: mart_revenue.sql
-- Schema: PETAL_CO_DW.MARTS
-- Description: Gross vs net revenue by channel, customer type,
--              and product category by week.
--              Key story: Subscription revenue is more predictable
--              and has lower return rates than one-time purchases.
-- =============================================================

WITH orders AS (
    SELECT
        ORDER_WEEK,
        ORDER_MONTH,
        ORDER_QUARTER,
        ORDER_YEAR,
        CHANNEL,
        COUNTRY,
        REGION,
        PRODUCT_CATEGORY,
        CUSTOMER_TYPE,
        IS_SUBSCRIBER,
        GROSS_REVENUE,
        DISCOUNT,
        NET_REVENUE,
        ADJUSTED_REVENUE,
        IS_RETURNED,
        IS_DISCOUNTED,
        IS_SUBSCRIPTION_ORDER
    FROM {{ ref('stg_orders') }}
),

weekly_revenue AS (
    SELECT
        ORDER_WEEK                                  AS WEEK,
        ORDER_MONTH                                 AS MONTH,
        ORDER_QUARTER                               AS QUARTER,
        ORDER_YEAR                                  AS YEAR,
        CHANNEL,
        COUNTRY,
        REGION,
        PRODUCT_CATEGORY,
        CUSTOMER_TYPE,
        IS_SUBSCRIBER,

        -- Volume
        COUNT(*)                                    AS TOTAL_ORDERS,
        SUM(IS_RETURNED)                            AS RETURNED_ORDERS,
        SUM(IS_SUBSCRIPTION_ORDER)                  AS SUBSCRIPTION_ORDERS,

        -- Revenue
        ROUND(SUM(GROSS_REVENUE), 2)                AS GROSS_REVENUE,
        ROUND(SUM(DISCOUNT), 2)                     AS TOTAL_DISCOUNTS,
        ROUND(SUM(NET_REVENUE), 2)                  AS NET_REVENUE,
        ROUND(SUM(ADJUSTED_REVENUE), 2)             AS ADJUSTED_REVENUE,

        -- Rates as decimal — format as % in Looker Studio
        ROUND(SUM(IS_RETURNED) / NULLIF(COUNT(*), 0), 4)
                                                    AS RETURN_RATE,
        ROUND(SUM(IS_DISCOUNTED) / NULLIF(COUNT(*), 0), 4)
                                                    AS DISCOUNT_RATE,
        ROUND(SUM(IS_SUBSCRIPTION_ORDER) / NULLIF(COUNT(*), 0), 4)
                                                    AS SUBSCRIPTION_ORDER_RATE,

        -- Average order values
        ROUND(AVG(GROSS_REVENUE), 2)                AS AVG_ORDER_VALUE,
        ROUND(AVG(NET_REVENUE), 2)                  AS AVG_NET_ORDER_VALUE,
        ROUND(AVG(ADJUSTED_REVENUE), 2)             AS AVG_ADJUSTED_ORDER_VALUE

    FROM orders
    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
)

SELECT * FROM weekly_revenue
ORDER BY WEEK, CHANNEL, CUSTOMER_TYPE