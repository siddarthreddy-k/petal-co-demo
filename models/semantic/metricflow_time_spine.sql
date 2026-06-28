{{
  config(materialized='table')
}}

with days as (
    {{ dbt.date_spine(
        'day',
        "to_date('2024-01-01', 'yyyy-mm-dd')",
        "to_date('2027-01-01', 'yyyy-mm-dd')"
    ) }}
)

select cast(date_day as date) as date_day
from days