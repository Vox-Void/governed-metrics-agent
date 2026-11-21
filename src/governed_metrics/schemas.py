"""Validate planner decisions and define the service response envelope."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Metric = Literal[
    "captured_amount", "refunded_amount", "net_collected", "payment_success_rate", "paying_orders"
]
Currency = Literal["ZAR", "USD"]
Provider = Literal["CARD", "EFT"]
Grouping = Literal["total", "day", "provider"]
Input = Literal["captures", "refunds", "attempts"]
Unit = Literal["minor_units", "count", "ratio"]
METRICS: tuple[Metric, ...] = (
    "captured_amount",
    "refunded_amount",
    "net_collected",
    "payment_success_rate",
    "paying_orders",
)
PROVIDERS: tuple[Provider, ...] = ("CARD", "EFT")
CURRENCIES: tuple[Currency, ...] = ("ZAR", "USD")
CLARIFICATIONS = {
    "AMBIGUOUS_METRIC": "Do you mean gross captured amount or net collected after settled refunds?",
    "AMBIGUOUS_PAYMENTS": "Do you mean captured amount, paying orders, or payment success rate?",
    "MULTIPLE_METRICS": "Which one metric would you like to see first?",
    "CURRENCY_REQUIRED": "Which currency should I use, ZAR or USD?",
    "DATE_REQUIRED": "What business date or date range should I use? Include the year if it is unclear.",
    "WINDOW_TOO_LONG": "Choose a window of up to 60 business dates.",
    "GROUP_REQUIRED": "Would you like a total, a daily breakdown, or a provider breakdown?",
    "UNSUPPORTED_GROUP": "This metric supports a total or daily breakdown. Which would you like?",
    "CONFIRM_PROVIDER": "Please confirm you want the CARD provider only.",
    "PROVIDER_REQUIRED": "Which provider should I use, CARD or EFT?",
}
ClarificationCode = Literal[
    "AMBIGUOUS_METRIC",
    "AMBIGUOUS_PAYMENTS",
    "MULTIPLE_METRICS",
    "CURRENCY_REQUIRED",
    "DATE_REQUIRED",
    "WINDOW_TOO_LONG",
    "GROUP_REQUIRED",
    "UNSUPPORTED_GROUP",
    "CONFIRM_PROVIDER",
    "PROVIDER_REQUIRED",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


# A plan carries one metric with its merchant, filters, and grouping.
class MetricPlan(Strict):
    kind: Literal["plan"]
    metric_id: Metric
    merchant: str
    currency: Currency
    start: date
    end: date
    grouping: Grouping
    provider: Provider | None


class Clarification(Strict):
    kind: Literal["clarification"]
    reason: ClarificationCode


class Unable(Strict):
    kind: Literal["unable"]
    reason: Literal["NO_CERTIFIED_METRIC", "PLANNER_UNAVAILABLE"]


# Use the kind field to select the model that validates each planner response.
Decision = Annotated[MetricPlan | Clarification | Unable, Field(discriminator="kind")]
DECISION = TypeAdapter[Decision](Decision)


class MetricRow(Strict):
    group: str | None
    value: int | str | None
    numerator: int | None = None
    denominator: int | None = None


class Watermark(Strict):
    loaded_at: datetime
    complete_through: date


# An answer includes the result, metric definition, query template, and snapshot details.
class Answer(Strict):
    status: Literal["ok"] = "ok"
    reason: Literal["VERIFIED_METRIC"] = "VERIFIED_METRIC"
    trace_id: str
    metric_id: Metric
    label: str
    definition: str
    catalog_version: str
    unit: Unit
    currency: Currency
    currency_default_used: bool = False
    merchant: str
    provider: Provider | None
    grouping: Grouping
    timezone: str
    start: date
    end: date
    rows: list[MetricRow]
    template_id: str
    query_hash: str
    snapshot_id: str
    required_inputs: tuple[Input, ...]
    watermarks: dict[str, Watermark]


class Clarify(Strict):
    status: Literal["clarify"] = "clarify"
    trace_id: str
    reason: ClarificationCode
    question: str


class Failure(Strict):
    status: Literal["denied", "stale", "unavailable"]
    trace_id: str
    reason: str


Response = Answer | Clarify | Failure
