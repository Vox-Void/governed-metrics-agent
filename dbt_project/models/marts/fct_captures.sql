select
    merchant_id, capture_id, order_id, attempt_id, provider, currency,
    status, settled_at, amount_minor, source_version,
    cast(timezone('Africa/Johannesburg', settled_at) as date) as business_date
from {{ ref('stg_captures') }}
qualify row_number() over (
    partition by merchant_id, capture_id
    order by source_version desc, ingested_at desc
) = 1
