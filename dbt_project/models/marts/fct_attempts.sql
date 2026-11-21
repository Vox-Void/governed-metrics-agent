select
    merchant_id, attempt_id, order_id, provider, currency, status,
    initiated_at, completed_at, source_version,
    cast(timezone('Africa/Johannesburg', completed_at) as date) as business_date
from {{ ref('stg_attempts') }}
qualify row_number() over (
    partition by merchant_id, attempt_id
    order by source_version desc, ingested_at desc
) = 1
