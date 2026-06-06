-- =============================================================
-- Petal & Co — Staging Layer
-- Model: stg_orders.sql
-- Schema: PETAL_CO_DW.STAGING
-- Description: Cleans RAW.ORDERS and adds derived fields.
--              Joins to stg_customers to bring in customer_type
--              and channel for downstream LTV analysis.
-- =============================================================

WITH base AS (
    SELECT
        ORDER_ID,
        CUSTOMER_ID,
        SUBSCRIPTION_ID,
        TRY_TO_DATE(ORDER_DATE)                 AS ORDER_DATE,
        LOWER(TRIM(PRODUCT_CATEGORY))           AS PRODUCT_CATEGORY,
        UPPER(TRIM(COUNTRY))                    AS COUNTRY,
        GROSS_REVENUE,
        DISCOUNT,
        NET_REVENUE,
        RETURNED,
        LOWER(TRIM(STATUS))                     AS STATUS,
        LOADED_AT
    FROM {{ source('raw', 'orders') }}
    WHERE ORDER_ID IS NOT NULL
),

customers AS (
    SELECT
        CUSTOMER_ID,
        ACQUISITION_CHANNEL,
        ACQUISITION_DATE,
        ACQUISITION_COHORT,
        CUSTOMER_TYPE,
        IS_SUBSCRIBER,
        CHANNEL_TYPE,
        REGION
    FROM {{ ref('stg_customers') }}
),

enriched AS (
    SELECT
        o.ORDER_ID,
        o.CUSTOMER_ID,
        o.SUBSCRIPTION_ID,
        o.ORDER_DATE,
        o.PRODUCT_CATEGORY,
        o.COUNTRY,
        o.GROSS_REVENUE,
        o.DISCOUNT,
        o.NET_REVENUE,
        o.RETURNED,
        o.STATUS,
        o.LOADED_AT,

        -- From customers
        c.ACQUISITION_CHANNEL                   AS CHANNEL,
        c.ACQUISITION_DATE,
        c.ACQUISITION_COHORT,
        c.CUSTOMER_TYPE,
        c.IS_SUBSCRIBER,
        c.CHANNEL_TYPE,
        c.REGION,

        -- Derived flags
        IFF(o.RETURNED = TRUE, 1, 0)::INTEGER            AS IS_RETURNED,
        IFF(o.DISCOUNT > 0,    1, 0)::INTEGER            AS IS_DISCOUNTED,
        IFF(o.SUBSCRIPTION_ID IS NOT NULL, 1, 0)::INTEGER AS IS_SUBSCRIPTION_ORDER,

        -- Date parts
        DATE_TRUNC('week',    o.ORDER_DATE)     AS ORDER_WEEK,
        DATE_TRUNC('month',   o.ORDER_DATE)     AS ORDER_MONTH,
        DATE_TRUNC('quarter', o.ORDER_DATE)     AS ORDER_QUARTER,
        DATE_PART('year',     o.ORDER_DATE)     AS ORDER_YEAR,

        -- Days since acquisition
        DATEDIFF('day', c.ACQUISITION_DATE, o.ORDER_DATE) AS DAYS_SINCE_ACQ,

        -- Adjusted revenue (net after full return)
        CASE
            WHEN o.RETURNED = TRUE
            THEN 0
            ELSE o.NET_REVENUE
        END                                     AS ADJUSTED_REVENUE

    FROM base o
    LEFT JOIN customers c ON o.CUSTOMER_ID = c.CUSTOMER_ID
)

SELECT * FROM enriched