"""
PlayDesk pricing-rule model.

A `PricingRule` row is one tunable that the rule-eval engine applies to a
booking quote. Five `rule_type` choices ship in v8 (peak_hours, day_of_week,
member_tier, min_duration, bracket_rate); the engine fans out to a strategy
class per type. ``params`` is a JSONField with a shape that depends on
``rule_type`` — each strategy validates its own subset.

Rules are store-scoped (the engine reads ``request.store``) and may target a
single ``Resource`` or, when ``applies_to_resource`` is null, every resource
in the store.
"""

from django.db import models

from core.models import Resource, Store


class RuleType(models.TextChoices):
    PEAK_HOURS = "peak_hours", "Peak hours"
    DAY_OF_WEEK = "day_of_week", "Day of week"
    MEMBER_TIER = "member_tier", "Member tier"
    MIN_DURATION = "min_duration", "Minimum duration"
    BRACKET_RATE = "bracket_rate", "Bracket rate"


class PricingRule(models.Model):
    """A single pricing rule.

    Evaluation order is ``(priority asc, id asc)``. ``stackable=False`` rules
    block subsequent ``stackable=False`` rules from firing (the engine tracks
    a "non-stackable fired" flag); ``stackable=True`` rules always fire when
    their strategy's ``applies()`` returns True.

    ``params`` shape is per-``rule_type`` and is validated server-side by
    ``RuleStrategy.validate_params`` (see ``pricing/strategies/``).
    """

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="pricing_rules")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    priority = models.PositiveSmallIntegerField(default=100)
    stackable = models.BooleanField(default=True)
    rule_type = models.CharField(max_length=20, choices=RuleType.choices)
    params = models.JSONField(default=dict)
    applies_to_resource = models.ForeignKey(
        Resource,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="pricing_rules",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "id"]
        indexes = [
            # Explicit `name=` on every index — v4 campaigns hit a CI flake
            # when Django generated nondeterministic index names across
            # parallel test workers.
            models.Index(fields=["store", "enabled"], name="pricing_rule_store_enabled_idx"),
            models.Index(fields=["store", "rule_type"], name="pricing_rule_store_type_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.store.name} / {self.name} ({self.rule_type})"
