-- GDPR Article 17 — Erasure Audit Log
-- The defensible "who / when / current state" record for every erasure request.
-- Joins the registry against the live activation layer to PROVE current state
-- matches the request (erased customers are genuinely suppressed).

select
    r.customer_id,
    r.status                                   as request_status,
    r.request_date,
    r.erased_at,
    r.erased_by,
    datediff('day', r.request_date, coalesce(r.erased_at, current_date()))
                                               as days_to_action,
    a.is_erased                                as currently_suppressed,
    -- Reconciliation flag: does the live pipeline state match the registry?
    case
        when r.status = 'erased'    and a.is_erased = true  then 'OK - erased & suppressed'
        when r.status = 'requested' and a.is_erased = false then 'OK - requested, not yet actioned'
        when a.customer_id is null                          then 'NO MATCH - id not in customer base'
        else 'MISMATCH - investigate'
    end                                        as reconciliation_status
from {{ ref('gdpr_erasure_registry') }} r
left join {{ ref('stg_activation_pii') }} a
    on r.customer_id = a.customer_id
order by r.request_date desc