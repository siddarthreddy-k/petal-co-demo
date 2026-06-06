-- =============================================================
-- Petal & Co — Staging Layer
-- Model: stg_ad_spend.sql
-- Schema: PETAL_CO_DW.STAGING
-- Description: Cleans RAW.AD_SPEND and adds derived date fields.
-- =============================================================

WITH base AS (
    SELECT
        TRY_TO_DATE(DATE)                       AS SPEND_DATE,
        LOWER(TRIM(CHANNEL))                    AS CHANNEL,
        SPEND_GBP,
        IMPRESSIONS,
        CLICKS,
        LOADED_AT
    FROM {{ source('raw', 'ad_spend') }}
    WHERE DATE IS NOT NULL
),

enriched AS (
    SELECT
        SPEND_DATE,
        CHANNEL,
        SPEND_GBP,
        IMPRESSIONS,
        CLICKS,
        LOADED_AT,

        -- Date parts
        DATE_TRUNC('week',    SPEND_DATE)       AS SPEND_WEEK,
        DATE_TRUNC('month',   SPEND_DATE)       AS SPEND_MONTH,
        DATE_TRUNC('quarter', SPEND_DATE)       AS SPEND_QUARTER,
        DATE_PART('year',     SPEND_DATE)       AS SPEND_YEAR,

        -- CTR
        CASE
            WHEN IMPRESSIONS > 0
            THEN ROUND(CLICKS / IMPRESSIONS, 4)
            ELSE NULL
        END                                     AS CTR,

        -- CPM
        CASE
            WHEN IMPRESSIONS > 0
            THEN ROUND(SPEND_GBP / IMPRESSIONS * 1000, 2)
            ELSE NULL
        END                                     AS CPM,

        -- CPC
        CASE
            WHEN CLICKS > 0
            THEN ROUND(SPEND_GBP / CLICKS, 2)
            ELSE NULL
        END                                     AS CPC

    FROM base
)

SELECT * FROM enriched