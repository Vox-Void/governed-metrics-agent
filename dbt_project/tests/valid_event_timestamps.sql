select 'capture' as relation, merchant_id, capture_id as event_id
from {{ ref('stg_captures') }}
where ingested_at is null or (status = 'settled') <> (settled_at is not null)
union all
select 'refund', merchant_id, refund_id
from {{ ref('stg_refunds') }}
where ingested_at is null or (status = 'settled') <> (settled_at is not null)
union all
select 'attempt', merchant_id, attempt_id
from {{ ref('stg_attempts') }}
where ingested_at is null or initiated_at is null
    or (status in ('succeeded', 'failed')) <> (completed_at is not null)
    or completed_at < initiated_at
