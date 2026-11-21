select 'capture' as relation, merchant_id, capture_id as event_id
from {{ source('fixture', 'capture_deliveries') }}
where (settled_at is not null and not regexp_matches(settled_at, '(Z|[+]00:00)$'))
    or not regexp_matches(ingested_at, '(Z|[+]00:00)$')
union all
select 'refund', merchant_id, refund_id
from {{ source('fixture', 'refund_deliveries') }}
where (settled_at is not null and not regexp_matches(settled_at, '(Z|[+]00:00)$'))
    or not regexp_matches(ingested_at, '(Z|[+]00:00)$')
union all
select 'attempt', merchant_id, attempt_id
from {{ source('fixture', 'attempt_deliveries') }}
where (completed_at is not null and not regexp_matches(completed_at, '(Z|[+]00:00)$'))
    or not regexp_matches(ingested_at, '(Z|[+]00:00)$')
    or not regexp_matches(initiated_at, '(Z|[+]00:00)$')
