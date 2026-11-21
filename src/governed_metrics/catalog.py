"""Load the versioned semantic catalog and validate its compiler dependencies."""

from functools import lru_cache

import yaml

from governed_metrics.schemas import (
    CURRENCIES,
    METRICS,
    PROVIDERS,
    Currency,
    Grouping,
    Input,
    Metric,
    Provider,
    Strict,
    Unit,
)
from governed_metrics.snapshots import ROOT

BUSINESS_TIMEZONE = "Africa/Johannesburg"
METRIC_RULES: dict[Metric, tuple[Unit, tuple[Input, ...]]] = {
    "captured_amount": ("minor_units", ("captures",)),
    "refunded_amount": ("minor_units", ("captures", "refunds")),
    "net_collected": ("minor_units", ("captures", "refunds")),
    "payment_success_rate": ("ratio", ("attempts",)),
    "paying_orders": ("count", ("captures",)),
}


class MetricDefinition(Strict):
    label: str
    definition: str
    unit: Unit
    inputs: list[Input]
    groups: list[Grouping]
    aliases: list[str]


class Catalog(Strict):
    version: str
    timezone: str
    currencies: list[Currency]
    providers: list[Provider]
    ambiguous: list[str]
    metrics: dict[Metric, MetricDefinition]


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    catalog = Catalog.model_validate(yaml.safe_load((ROOT / "metrics/catalog.yml").read_bytes()))
    # Check the file's dimension values against the lists used by the compiler.
    if (
        set(catalog.metrics) != set(METRICS)
        or tuple(catalog.currencies) != CURRENCIES
        or tuple(catalog.providers) != PROVIDERS
        or catalog.timezone != BUSINESS_TIMEZONE
    ):
        raise ValueError("Catalog dimensions differ from the approved compiler dimensions.")
    # Reserve ambiguous terms and check each metric's inputs, groupings, and aliases.
    aliases = set(catalog.ambiguous)
    for metric, definition in catalog.metrics.items():
        policy_groups = (
            {"total", "day"} if metric == "paying_orders" else {"total", "day", "provider"}
        )
        if (
            METRIC_RULES[metric] != (definition.unit, tuple(definition.inputs))
            or set(definition.groups) != policy_groups
            or not definition.aliases
            or aliases.intersection(definition.aliases)
            or len(set(definition.aliases)) != len(definition.aliases)
        ):
            raise ValueError(f"Catalog definition is inconsistent for {metric}.")
        aliases.update(definition.aliases)
    return catalog
