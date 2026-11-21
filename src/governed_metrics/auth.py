"""Represent entitlements resolved by the trusted service launcher."""

from dataclasses import dataclass

from governed_metrics.schemas import METRICS, PROVIDERS, Currency, Grouping, Metric, Provider


@dataclass(frozen=True)
class Principal:
    merchant: str
    metrics: frozenset[Metric]
    groups: frozenset[Grouping]
    providers: frozenset[Provider]
    default_currency: Currency | None = None


PROFILES = {
    "analyst-a": Principal(
        "a", frozenset(METRICS), frozenset({"total", "day", "provider"}), frozenset(PROVIDERS)
    ),
    "analyst-b": Principal(
        "b", frozenset(METRICS), frozenset({"total", "day", "provider"}), frozenset(PROVIDERS)
    ),
    "ops-a": Principal(
        "a", frozenset({"payment_success_rate"}), frozenset({"total", "day"}), frozenset({"CARD"})
    ),
}
