SELECT *
FROM {{ ref('stg_orders') }}
WHERE net_revenue < 0
  AND returned = FALSE