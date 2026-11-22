select
    cast(merchant_id as varchar) as merchant_id,
    cast(capture_id as varchar) as capture_id,
    cast(order_id as varchar) as order_id,
    cast(attempt_id as varchar) as attempt_id,
    cast(provider as varchar) as provider,
    cast(currency as varchar) as currency,
    cast(status as varchar) as status,
    cast(nullif(settled_at, '') as timestamptz) as settled_at,
    case when regexp_full_match(amount_minor, '[0-9]+') then try_cast(amount_minor as bigint) end as amount_minor,
    case when regexp_full_match(version, '[0-9]+') then try_cast(version as bigint) end as source_version,
    cast(ingested_at as timestamptz) as ingested_at
from {{ source('fixture', 'capture_deliveries') }}
