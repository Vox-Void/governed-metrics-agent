select 'capture' as relation, merchant_id, capture_id as event_id, source_version
from {{ ref('stg_captures') }}
group by merchant_id, capture_id, source_version
having count(distinct (order_id, attempt_id, provider, currency, status, settled_at, amount_minor)) > 1
union all
select 'refund', merchant_id, refund_id, source_version
from {{ ref('stg_refunds') }}
group by merchant_id, refund_id, source_version
having count(distinct (capture_id, currency, status, settled_at, amount_minor)) > 1
union all
select 'attempt', merchant_id, attempt_id, source_version
from {{ ref('stg_attempts') }}
group by merchant_id, attempt_id, source_version
having count(distinct (order_id, provider, currency, status, initiated_at, completed_at)) > 1
