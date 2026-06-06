-- =============================================================
-- Petal & Co — Mart Layer
-- Model: mart_cac.sql
-- Schema: PETAL_CO_DW.MARTS
-- Description: Blended CAC per channel per month.
--              Also shows subscription rate per channel —
--              the key insight that Meta's high CAC buys
--              mostly one-time customers with low LTV.
--              Key story: Meta CAC inflates ~55% Jan to Dec
--              while acquiring only 25% subscribers vs
--              email/organic acquiring 65-70% subscribers.
-- =============================================================

WITH monthly_spend AS (
    SELECT
        SPEND_MONTH                             AS MONTH,
        CHANNEL,
        SUM(SPEND_GBP)                          AS TOTAL_SPEND
    FROM {{ ref('stg_ad_spend') }}
    GROUP BY 1, 2
),

new_customers AS (
    SELECT
        DATE_TRUNC('month', ACQUISITION_DATE)   AS MONTH,
        ACQUISITION_CHANNEL                     AS CHANNEL,
        COUNT(DISTINCT CUSTOMER_ID)             AS NEW_CUSTOMERS,
        SUM(CASE WHEN IS_SUBSCRIBER = 1 THEN 1 ELSE 0 END)
                                                AS NEW_SUBSCRIBERS,
        SUM(CASE WHEN IS_SUBSCRIBER = 0 THEN 1 ELSE 0 END)
                                                AS NEW_ONE_TIME
    FROM {{ ref('stg_customers') }}
    WHERE ACQUISITION_CHANNEL IN ('meta', 'google', 'tiktok')
    GROUP BY 1, 2
),

joined AS (
    SELECT
        s.MONTH,
        s.CHANNEL,
        s.TOTAL_SPEND,
        COALESCE(c.NEW_CUSTOMERS, 0)            AS NEW_CUSTOMERS,
        COALESCE(c.NEW_SUBSCRIBERS, 0)          AS NEW_SUBSCRIBERS,
        COALESCE(c.NEW_ONE_TIME, 0)             AS NEW_ONE_TIME,

        -- CAC = spend / new customers
        CASE
            WHEN COALESCE(c.NEW_CUSTOMERS, 0) > 0
            THEN ROUND(s.TOTAL_SPEND / c.NEW_CUSTOMERS, 2)
            ELSE NULL
        END                                     AS CAC_GBP,

        -- Subscription rate as decimal — format as % in Looker Studio
        CASE
            WHEN COALESCE(c.NEW_CUSTOMERS, 0) > 0
            THEN ROUND(c.NEW_SUBSCRIBERS / c.NEW_CUSTOMERS, 4)
            ELSE NULL
        END                                     AS SUBSCRIBER_RATE,

        -- Subscriber CAC — spend per new subscriber acquired
        CASE
            WHEN COALESCE(c.NEW_SUBSCRIBERS, 0) > 0
            THEN ROUND(s.TOTAL_SPEND / c.NEW_SUBSCRIBERS, 2)
            ELSE NULL
        END                                     AS SUBSCRIBER_CAC_GBP

    FROM monthly_spend s
    LEFT JOIN new_customers c
        ON s.MONTH  = c.MONTH
        AND s.CHANNEL = c.CHANNEL
)

SELECT
    MONTH,
    CHANNEL,
    TOTAL_SPEND,
    NEW_CUSTOMERS,
    NEW_SUBSCRIBERS,
    NEW_ONE_TIME,
    CAC_GBP,
    SUBSCRIBER_RATE,
    SUBSCRIBER_CAC_GBP,

    -- Month over month CAC change (absolute)
    CAC_GBP - LAG(CAC_GBP) OVER (
        PARTITION BY CHANNEL ORDER BY MONTH
    )                                           AS CAC_MOM_CHANGE,

    -- MoM % change as decimal — format as % in Looker Studio
    CASE
        WHEN LAG(CAC_GBP) OVER (PARTITION BY CHANNEL ORDER BY MONTH) > 0
        THEN ROUND(
            (CAC_GBP - LAG(CAC_GBP) OVER (PARTITION BY CHANNEL ORDER BY MONTH))
            / LAG(CAC_GBP) OVER (PARTITION BY CHANNEL ORDER BY MONTH), 4)
        ELSE NULL
    END                                         AS CAC_MOM_PCT_CHANGE

FROM joined
ORDER BY MONTH, CHANNEL