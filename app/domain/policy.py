import hashlib
from decimal import Decimal
from typing import Self

import yaml
from pydantic import BaseModel, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ValidationError

_WEIGHT_SUM_TOLERANCE = Decimal("0.001")


class BucketConfig(BaseModel, frozen=True):
    targets: dict[str, Decimal]

    @field_validator("targets")
    @classmethod
    def validate_targets_not_empty(cls, v: dict[str, Decimal]) -> dict[str, Decimal]:
        if not v:
            raise ValueError("targets must not be empty")
        return v

    @field_validator("targets")
    @classmethod
    def validate_target_weights_positive(cls, v: dict[str, Decimal]) -> dict[str, Decimal]:
        for ticker, weight in v.items():
            if weight <= Decimal("0"):
                raise ValueError(f"Weight for '{ticker}' must be positive, got {weight}")
            if weight > Decimal("1"):
                raise ValueError(f"Weight for '{ticker}' must be <= 1.0, got {weight}")
        return v

    @field_validator("targets")
    @classmethod
    def normalize_tickers(cls, v: dict[str, Decimal]) -> dict[str, Decimal]:
        return dict(sorted((ticker.upper(), weight) for ticker, weight in v.items()))


class BucketsConfig(BaseModel, frozen=True):
    core: BucketConfig
    satellite: BucketConfig | None = None


class ConstraintsConfig(BaseModel, frozen=True):
    min_trade_value: Decimal = Decimal("0")
    max_position_weight: Decimal = Decimal("1")
    no_sell: bool = False

    @field_validator("min_trade_value")
    @classmethod
    def validate_min_trade_non_negative(cls, v: Decimal) -> Decimal:
        if v < Decimal("0"):
            raise ValueError(f"min_trade_value must be >= 0, got {v}")
        return v

    @field_validator("max_position_weight")
    @classmethod
    def validate_max_position_weight_range(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0") or v > Decimal("1"):
            raise ValueError(f"max_position_weight must be in (0, 1.0], got {v}")
        return v


class RebalancingConfig(BaseModel, frozen=True):
    drift_soft: Decimal = Decimal("0.05")
    drift_hard: Decimal = Decimal("0.10")

    @field_validator("drift_soft", "drift_hard")
    @classmethod
    def validate_drift_range(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0") or v >= Decimal("1"):
            raise ValueError(f"Drift threshold must be in (0, 1.0), got {v}")
        return v

    @model_validator(mode="after")
    def validate_soft_le_hard(self) -> Self:
        if self.drift_soft > self.drift_hard:
            raise ValueError(f"drift_soft ({self.drift_soft}) must be <= drift_hard ({self.drift_hard})")
        return self


class CostsConfig(BaseModel, frozen=True):
    commission_fixed: Decimal = Decimal("0")
    fx_spread_bps: int = 0

    @field_validator("commission_fixed")
    @classmethod
    def validate_commission_non_negative(cls, v: Decimal) -> Decimal:
        if v < Decimal("0"):
            raise ValueError(f"commission_fixed must be >= 0, got {v}")
        return v

    @field_validator("fx_spread_bps")
    @classmethod
    def validate_fx_spread_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"fx_spread_bps must be >= 0, got {v}")
        return v


class PolicyConfig(BaseModel, frozen=True):
    """Parsed and validated investment policy configuration.

    policy_hash is the SHA-256 hex digest of the raw YAML text,
    computed before parsing.
    """

    base_currency: str
    buckets: BucketsConfig
    constraints: ConstraintsConfig = ConstraintsConfig()
    rebalancing: RebalancingConfig = RebalancingConfig()
    costs: CostsConfig = CostsConfig()
    policy_hash: str

    @field_validator("base_currency")
    @classmethod
    def validate_base_currency(cls, v: str) -> str:
        v = v.upper().strip()
        if len(v) != 3 or not v.isalpha():
            raise ValueError(f"base_currency must be a 3-letter currency code, got '{v}'")
        return v

    @model_validator(mode="after")
    def validate_core_weights_sum(self) -> Self:
        total = sum(self.buckets.core.targets.values())
        if abs(total - Decimal("1")) > _WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                f"Core bucket target weights must sum to 1.0 (tolerance {_WEIGHT_SUM_TOLERANCE}), got {total}"
            )
        return self

    @model_validator(mode="after")
    def validate_satellite_weights_sum(self) -> Self:
        if self.buckets.satellite is not None:
            total = sum(self.buckets.satellite.targets.values())
            if abs(total - Decimal("1")) > _WEIGHT_SUM_TOLERANCE:
                raise ValueError(
                    f"Satellite bucket target weights must sum to 1.0 (tolerance {_WEIGHT_SUM_TOLERANCE}), got {total}"
                )
        return self

    @model_validator(mode="after")
    def validate_no_ticker_overlap(self) -> Self:
        if self.buckets.satellite is not None:
            core_tickers = set(self.buckets.core.targets.keys())
            sat_tickers = set(self.buckets.satellite.targets.keys())
            overlap = core_tickers & sat_tickers
            if overlap:
                raise ValueError(f"Tickers must not appear in both core and satellite: {sorted(overlap)}")
        return self


def parse_policy_yaml(yaml_text: str) -> PolicyConfig:
    """Parse raw YAML text into a validated PolicyConfig.

    Computes SHA-256 hash of the raw yaml_text before parsing.

    Raises:
        ValidationError: If YAML syntax is invalid or policy validation fails.
    """
    yaml_text = yaml_text.strip()
    if not yaml_text:
        raise ValidationError(message="Policy YAML is empty")

    policy_hash = hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()

    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise ValidationError(message="Invalid YAML syntax", details=str(e)) from e

    if not isinstance(data, dict):
        raise ValidationError(
            message="Policy YAML must be a mapping (key-value pairs)",
            details=f"Got {type(data).__name__} instead",
        )

    data["policy_hash"] = policy_hash

    try:
        return PolicyConfig.model_validate(data)
    except PydanticValidationError as e:
        raise ValidationError(message="Invalid policy configuration", details=str(e)) from e
