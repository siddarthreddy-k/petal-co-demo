{{ config(materialized='table') }}
 
-- Clean, single-grain (ONE ROW PER CUSTOMER) mart over the ML churn source.
-- The agent queries THIS, never the ML source directly (P3 principle 2).
--
-- Columns confirmed against _ml_sources.yml:
--   CUSTOMER_ID, CHURN_PROBABILITY, RISK_BAND_LABEL (Low/Medium/High),
--   TOP_CHURN_DRIVER, IS_CHURNED, ESTIMATED_MRR (£, 0 when inactive).
-- No numeric RISK_BAND (not in source). No scoring date in source, so we
-- stamp the run date to give MetricFlow a time anchor.
 
with churn_source as (
    select * from {{ source('ml', 'ML_CHURN_RISK_SCORES') }}
)
 
select
    customer_id,
 
    -- risk classification
    risk_band_label,                             -- 'Low' / 'Medium' / 'High'
    top_churn_driver,
 
    -- prediction
    churn_probability,                           -- 0..1
 
    -- has this subscriber already churned? (already-lost vs still-at-risk)
    is_churned,
 
    -- MRR (0 when inactive; summing gives active MRR)
    estimated_mrr,
 
    -- derived flags
    case when risk_band_label = 'High' then 1 else 0 end as is_high_risk,
    case when risk_band_label = 'High' then estimated_mrr else 0 end as high_risk_mrr,
 
    -- time anchor for MetricFlow (no scoring date exists in the source)
    cast(current_date() as date) as score_date
 
from churn_source