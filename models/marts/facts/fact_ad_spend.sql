-- =============================================================
-- Petal & Co — Fact Layer
-- Model: fct_ad_spend.sql
-- Schema: PETAL_CO_DW.MARTS
-- Description: Ad spend fact table.
--              One row per channel per day with efficiency metrics.
--              BI tool joins to dim_dates at query time.
-- =============================================================

WITH ad_spend AS (
    SELECT
        SPEND_DATE,
        SPEND_WEEK,
        SPEND_MONTH,
        SPEND_QUARTER,
        SPEND_YEAR,
        CHANNEL,
        SPEND_GBP,
        IMPRESSIONS,
        CLICKS,
        CTR,
        CPM,
        CPC
    FROM {{ ref('stg_ad_spend') }}
)

SELECT
    -- Keys
    SPEND_DATE,
    CHANNEL,

    -- Date parts
    SPEND_WEEK,
    SPEND_MONTH,
    SPEND_QUARTER,
    SPEND_YEAR,

    -- Spend measures
    SPEND_GBP,
    IMPRESSIONS,
    CLICKS,

    -- Efficiency metrics
    CTR,
    CPM,
    CPC

FROM ad_spend
ORDER BY SPEND_DATE, CHANNEL