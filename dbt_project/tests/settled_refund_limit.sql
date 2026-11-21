select c.merchant_id, c.capture_id
from {{ ref('fct_captures') }} as c
join {{ ref('fct_refunds') }} as r
    on c.merchant_id = r.merchant_id and c.capture_id = r.capture_id
where r.status = 'settled'
group by c.merchant_id, c.capture_id, c.amount_minor
having sum(r.amount_minor) > c.amount_minor
