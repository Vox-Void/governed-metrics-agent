select
    cast(merchant_id as varchar) as merchant_id,
    cast(refund_id as varchar) as refund_id,
    cast(capture_id as varchar) as capture_id,
    cast(currency as varchar) as currency,
    cast(status as varchar) as status,
    cast(nullif(settled_at, '') as timestamptz) as settled_at,
    cast(amount_minor as bigint) as amount_minor,
    cast(version as bigint) as source_version,
    cast(ingested_at as timestamptz) as ingested_at
from {{ source('fixture', 'refund_deliveries') }}
