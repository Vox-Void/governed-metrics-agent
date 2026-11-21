select 'capture' as relation, merchant_id, capture_id as event_id
from {{ ref('fct_captures') }}
group by merchant_id, capture_id
having count(*) <> 1 or merchant_id is null or capture_id is null
union all
select 'refund', merchant_id, refund_id
from {{ ref('fct_refunds') }}
group by merchant_id, refund_id
having count(*) <> 1 or merchant_id is null or refund_id is null
union all
select 'attempt', merchant_id, attempt_id
from {{ ref('fct_attempts') }}
group by merchant_id, attempt_id
having count(*) <> 1 or merchant_id is null or attempt_id is null
