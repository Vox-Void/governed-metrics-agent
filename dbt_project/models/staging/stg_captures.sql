select
    cast(merchant_id as varchar) as merchant_id,
    cast(capture_id as varchar) as capture_id,
    cast(order_id as varchar) as order_id,
    cast(attempt_id as varchar) as attempt_id,
    cast(provider as varchar) as provider,
    cast(currency as varchar) as currency,
    cast(status as varchar) as status,
    cast(nullif(settled_at, '') as timestamptz) as settled_at,
    cast(amount_minor as bigint) as amount_minor,
    cast(version as bigint) as source_version,
    cast(ingested_at as timestamptz) as ingested_at
from {{ source('fixture', 'capture_deliveries') }}
