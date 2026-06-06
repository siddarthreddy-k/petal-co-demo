-- =============================================================
-- Petal & Co — Dimensional Layer
-- Model: dim_dates.sql
-- Schema: PETAL_CO_DW.MARTS
-- Description: Date dimension table for 2024.
--              Covers the full Petal & Co data range.
-- =============================================================

WITH date_spine AS (
    SELECT
        DATEADD('day', SEQ4(), '2024-01-01'::DATE) AS DATE_DAY
    FROM TABLE(GENERATOR(ROWCOUNT => 366))
    WHERE DATEADD('day', SEQ4(), '2024-01-01'::DATE) <= '2024-12-31'::DATE
)

SELECT
    DATE_DAY,
    DATE_PART('year',    DATE_DAY)              AS YEAR,
    DATE_PART('quarter', DATE_DAY)              AS QUARTER,
    DATE_PART('month',   DATE_DAY)              AS MONTH_NUMBER,
    MONTHNAME(DATE_DAY)                         AS MONTH_NAME,
    DATE_PART('week',    DATE_DAY)              AS WEEK_NUMBER,
    DATE_PART('day',     DATE_DAY)              AS DAY_OF_MONTH,
    DAYNAME(DATE_DAY)                           AS DAY_NAME,
    DATE_PART('dayofweek', DATE_DAY)            AS DAY_OF_WEEK,

    -- Date truncations
    DATE_TRUNC('week',    DATE_DAY)             AS WEEK_START,
    DATE_TRUNC('month',   DATE_DAY)             AS MONTH_START,
    DATE_TRUNC('quarter', DATE_DAY)             AS QUARTER_START,

    -- Flags
    CASE WHEN DAYNAME(DATE_DAY) IN ('Sat', 'Sun')
         THEN TRUE ELSE FALSE END               AS IS_WEEKEND,

    -- Quarter label
    'Q' || DATE_PART('quarter', DATE_DAY)
    || ' ' || DATE_PART('year', DATE_DAY)       AS QUARTER_LABEL,

    -- Month label
    MONTHNAME(DATE_DAY)
    || ' ' || DATE_PART('year', DATE_DAY)       AS MONTH_LABEL

FROM date_spine
ORDER BY DATE_DAY