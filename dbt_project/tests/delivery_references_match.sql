select 'capture' as relation, c.merchant_id, c.capture_id as event_id
from {{ ref('fct_captures') }} as c
left join {{ ref('fct_attempts') }} as a
    on c.merchant_id = a.merchant_id and c.attempt_id = a.attempt_id
where a.attempt_id is null or c.currency is distinct from a.currency
    or c.provider is distinct from a.provider or c.order_id is distinct from a.order_id
    or (c.status = 'settled' and a.status <> 'succeeded')
union all
select 'refund', r.merchant_id, r.refund_id
from {{ ref('stg_refunds') }} as r
left join {{ ref('fct_captures') }} as c
    on r.merchant_id = c.merchant_id and r.capture_id = c.capture_id
where c.capture_id is null or r.currency is distinct from c.currency
    or (r.status = 'settled' and c.status <> 'settled')
