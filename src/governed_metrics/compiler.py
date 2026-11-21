"""Compile approved metric plans into fixed SQL variants and bound parameters."""

import hashlib
from dataclasses import dataclass

from governed_metrics.schemas import Grouping, MetricPlan

FILTER = "merchant_id = ? and currency = ? and business_date >= cast(? as date) and business_date < cast(? as date)"
GROUP_EXPRESSION: dict[Grouping, str] = {
    "total": "cast(null as varchar)",
    "day": "cast(business_date as varchar)",
    "provider": "provider",
}


@dataclass(frozen=True)
class Statement:
    template_id: str
    sql: str
    parameters: tuple[str, ...]

    @property
    def digest(self) -> str:
        """Hash the SQL template after collapsing whitespace."""
        return hashlib.sha256(" ".join(self.sql.split()).encode()).hexdigest()


def compile_metric(plan: MetricPlan) -> Statement:
    group = GROUP_EXPRESSION[plan.grouping]
    grouping = " group by 1" if plan.grouping != "total" else ""
    terms = FILTER + (" and provider = ?" if plan.provider is not None else "")
    # Keep the filter values in the order of the SQL placeholders.
    params: tuple[str, ...] = (
        plan.merchant,
        plan.currency,
        plan.start.isoformat(),
        plan.end.isoformat(),
    )
    if plan.provider is not None:
        params += (plan.provider,)

    def settled(fact: str, measure: str) -> str:
        return f"select {group} as bucket, {measure} as value from {fact} where {terms} and status = 'settled'{grouping}"

    match plan.metric_id:
        case "captured_amount":
            sql = settled("fct_captures", "coalesce(sum(amount_minor), 0)")
        case "refunded_amount":
            sql = settled("fct_refunds", "coalesce(sum(amount_minor), 0)")
        case "paying_orders":
            sql = settled("fct_captures", "count(distinct order_id)")
        case "payment_success_rate":
            sql = f"""select {group} as bucket,
                    count(*) filter (where status = 'succeeded') as numerator,
                    count(*) as denominator
                from fct_attempts where {terms} and status in ('succeeded', 'failed'){grouping}"""
        case "net_collected":
            # Add the capture and negative refund totals after grouping each stream separately.
            captured = settled("fct_captures", "coalesce(sum(amount_minor), 0)")
            refunded = settled("fct_refunds", "-coalesce(sum(amount_minor), 0)")
            sql = f"""with captured as ({captured}), refunded as ({refunded}),
                movements as (select * from captured union all select * from refunded)
                select bucket, sum(value) as value from movements group by bucket"""
            # Bind the same scope again for the separate refund scan.
            params += params
    suffix = ".filtered" if plan.provider else ""
    return Statement(f"{plan.metric_id}.{plan.grouping}{suffix}", sql, params)
