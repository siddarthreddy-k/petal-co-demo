-- =============================================================
-- Petal & Co — Dimensional Layer
-- Model: dim_products.sql
-- Schema: PETAL_CO_DW.MARTS
-- Description: Product dimension table.
--              Static reference for product categories,
--              base AOV, and subscription eligibility.
-- =============================================================

WITH products AS (
    SELECT * FROM (VALUES
        ('skincare',        'Skincare',         45.00,  TRUE,   'Beauty'),
        ('supplements',     'Supplements',      35.00,  TRUE,   'Wellness'),
        ('haircare',        'Haircare',         40.00,  TRUE,   'Beauty'),
        ('wellness_bundle', 'Wellness Bundle',  75.00,  TRUE,   'Wellness')
    ) AS t (
        PRODUCT_CATEGORY_KEY,
        PRODUCT_CATEGORY_NAME,
        BASE_AOV_GBP,
        IS_SUBSCRIPTION_ELIGIBLE,
        PRODUCT_DIVISION
    )
)

SELECT
    PRODUCT_CATEGORY_KEY,
    PRODUCT_CATEGORY_NAME,
    BASE_AOV_GBP,
    IS_SUBSCRIPTION_ELIGIBLE,
    PRODUCT_DIVISION
FROM products