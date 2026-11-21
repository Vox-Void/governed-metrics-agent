with latest as (
    select * from {{ ref('stg_refunds') }}
    qualify row_number() over (
        partition by merchant_id, refund_id
        order by source_version desc, ingested_at desc
    ) = 1
)
select
    r.merchant_id, r.refund_id, r.capture_id, c.provider, c.currency,
    r.status, r.settled_at, r.amount_minor, r.source_version,
    cast(timezone('Africa/Johannesburg', r.settled_at) as date) as business_date
from latest as r
join {{ ref('fct_captures') }} as c
    on r.merchant_id = c.merchant_id and r.capture_id = c.capture_id
