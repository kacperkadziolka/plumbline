import hashlib
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ValidationError


class Contribution(BaseModel, frozen=True):
    """A single contribution event: a dated cash inflow."""

    date: date
    amount: Decimal
    currency: str

    @field_validator("amount")
    @classmethod
    def validate_amount_positive(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0"):
            raise ValueError(f"amount must be positive, got {v}")
        return v

    @field_validator("currency")
    @classmethod
    def validate_currency_format(cls, v: str) -> str:
        v = v.upper().strip()
        if len(v) != 3 or not v.isalpha():
            raise ValueError(f"currency must be a 3-letter code, got '{v}'")
        return v


class MonthlySchedule(BaseModel, frozen=True):
    """Fixed monthly contribution schedule."""

    type: Literal["monthly"] = "monthly"
    amount: Decimal
    currency: str
    day_of_month: int = 1

    @field_validator("amount")
    @classmethod
    def validate_amount_positive(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0"):
            raise ValueError(f"amount must be positive, got {v}")
        return v

    @field_validator("currency")
    @classmethod
    def validate_currency_format(cls, v: str) -> str:
        v = v.upper().strip()
        if len(v) != 3 or not v.isalpha():
            raise ValueError(f"currency must be a 3-letter code, got '{v}'")
        return v

    @field_validator("day_of_month")
    @classmethod
    def validate_day_range(cls, v: int) -> int:
        if v < 1 or v > 28:
            raise ValueError(f"day_of_month must be between 1 and 28, got {v}")
        return v


class CsvSchedule(BaseModel, frozen=True):
    """Contribution schedule loaded from CSV data."""

    type: Literal["csv"] = "csv"
    contributions: list[Contribution]

    @field_validator("contributions")
    @classmethod
    def validate_contributions_not_empty(cls, v: list[Contribution]) -> list[Contribution]:
        if not v:
            raise ValueError("contributions must not be empty")
        return v


ContributionSchedule = Annotated[MonthlySchedule | CsvSchedule, Field(discriminator="type")]


class BacktestConfig(BaseModel, frozen=True):
    """Validated backtest configuration.

    config_hash is the SHA-256 hex digest of the raw YAML text,
    computed before parsing (following PolicyConfig pattern).
    """

    start_date: date
    end_date: date
    contribution_schedule: ContributionSchedule
    config_hash: str

    @model_validator(mode="after")
    def validate_date_ordering(self) -> Self:
        if self.start_date >= self.end_date:
            raise ValueError(f"start_date ({self.start_date}) must be before end_date ({self.end_date})")
        return self


def parse_backtest_yaml(yaml_text: str) -> BacktestConfig:
    """Parse raw YAML text into a validated BacktestConfig.

    Computes SHA-256 hash of the raw yaml_text before parsing.

    Raises:
        ValidationError: If YAML syntax is invalid or config validation fails.
    """
    yaml_text = yaml_text.strip()
    if not yaml_text:
        raise ValidationError(message="Backtest YAML is empty")

    config_hash = hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()

    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise ValidationError(message="Invalid YAML syntax", details=str(e)) from e

    if not isinstance(data, dict):
        raise ValidationError(
            message="Backtest YAML must be a mapping (key-value pairs)",
            details=f"Got {type(data).__name__} instead",
        )

    data["config_hash"] = config_hash

    try:
        return BacktestConfig.model_validate(data)
    except PydanticValidationError as e:
        raise ValidationError(message="Invalid backtest configuration", details=str(e)) from e
