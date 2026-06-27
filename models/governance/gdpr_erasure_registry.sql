-- Append-only registry of Article 17 erasure requests. This IS the audit trail.

select
    customer_id,
    request_date,
    erased_at,
    erased_by,
    status              -- 'requested' | 'erased'
from {{ ref('seed_erasure_requests') }}