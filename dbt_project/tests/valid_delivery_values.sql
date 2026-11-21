select 'capture' as relation, merchant_id, capture_id as event_id
from {{ ref('stg_captures') }}
where coalesce(provider, '') not in ('CARD', 'EFT')
    or coalesce(currency, '') not in ('ZAR', 'USD')
    or coalesce(status, '') not in ('settled', 'pending')
    or coalesce(amount_minor, -1) < 0 or coalesce(source_version, 0) < 1
    or order_id is null or attempt_id is null
union all
select 'refund', merchant_id, refund_id
from {{ ref('stg_refunds') }}
where coalesce(currency, '') not in ('ZAR', 'USD')
    or coalesce(status, '') not in ('settled', 'pending')
    or coalesce(amount_minor, -1) < 0 or coalesce(source_version, 0) < 1
    or capture_id is null
union all
select 'attempt', merchant_id, attempt_id
from {{ ref('stg_attempts') }}
where coalesce(provider, '') not in ('CARD', 'EFT')
    or coalesce(currency, '') not in ('ZAR', 'USD')
    or coalesce(status, '') not in ('succeeded', 'failed', 'pending')
    or coalesce(source_version, 0) < 1 or order_id is null
