import hashlib
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ValidationError
from app.domain.backtest import Contribution, CsvSchedule, MonthlySchedule, parse_backtest_yaml

MINIMAL_MONTHLY_YAML = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: monthly
  amount: 1000.00
  currency: EUR
  day_of_month: 15
"""

CSV_SCHEDULE_YAML = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: csv
  contributions:
    - date: 2020-01-15
      amount: 1000.00
      currency: EUR
    - date: 2020-02-15
      amount: 1500.00
      currency: EUR
"""


# --- Happy path: monthly schedule ---


def test_parse_monthly_schedule():
    """Parse a minimal monthly contribution backtest config."""
    config = parse_backtest_yaml(MINIMAL_MONTHLY_YAML)

    assert config.start_date == date(2020, 1, 1)
    assert config.end_date == date(2024, 12, 31)
    assert isinstance(config.contribution_schedule, MonthlySchedule)
    assert config.contribution_schedule.type == "monthly"
    assert config.contribution_schedule.amount == Decimal("1000")
    assert config.contribution_schedule.currency == "EUR"
    assert config.contribution_schedule.day_of_month == 15


def test_parse_monthly_default_day():
    """day_of_month defaults to 1 when omitted."""
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: monthly
  amount: 500
  currency: USD
"""
    config = parse_backtest_yaml(yaml_text)

    assert config.contribution_schedule.day_of_month == 1


def test_monthly_currency_normalized_uppercase():
    """Monthly schedule currency is uppercased."""
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: monthly
  amount: 1000
  currency: eur
  day_of_month: 1
"""
    config = parse_backtest_yaml(yaml_text)

    assert config.contribution_schedule.currency == "EUR"


# --- Happy path: CSV schedule ---


def test_parse_csv_schedule():
    """Parse a backtest config with inline CSV contributions."""
    config = parse_backtest_yaml(CSV_SCHEDULE_YAML)

    assert isinstance(config.contribution_schedule, CsvSchedule)
    assert config.contribution_schedule.type == "csv"
    assert len(config.contribution_schedule.contributions) == 2
    c0 = config.contribution_schedule.contributions[0]
    assert c0.date == date(2020, 1, 15)
    assert c0.amount == Decimal("1000")
    assert c0.currency == "EUR"


def test_csv_contribution_currency_normalized():
    """Contribution currencies are uppercased."""
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: csv
  contributions:
    - date: 2020-01-15
      amount: 1000
      currency: usd
"""
    config = parse_backtest_yaml(yaml_text)

    assert config.contribution_schedule.contributions[0].currency == "USD"


# --- Hash computation ---


def test_config_hash_is_sha256():
    """config_hash is SHA-256 of the stripped YAML text."""
    stripped = MINIMAL_MONTHLY_YAML.strip()
    expected = hashlib.sha256(stripped.encode("utf-8")).hexdigest()
    config = parse_backtest_yaml(MINIMAL_MONTHLY_YAML)

    assert config.config_hash == expected
    assert len(config.config_hash) == 64


def test_config_hash_differs_for_different_content():
    """Different YAML text produces different hashes."""
    config1 = parse_backtest_yaml(MINIMAL_MONTHLY_YAML)
    config2 = parse_backtest_yaml(CSV_SCHEDULE_YAML)

    assert config1.config_hash != config2.config_hash


# --- Determinism ---


def test_parse_is_deterministic():
    """Same input always produces identical output."""
    config1 = parse_backtest_yaml(MINIMAL_MONTHLY_YAML)
    config2 = parse_backtest_yaml(MINIMAL_MONTHLY_YAML)

    assert config1 == config2
    assert config1.config_hash == config2.config_hash


# --- Date validation ---


def test_start_date_equals_end_date_raises():
    """start_date == end_date is rejected."""
    yaml_text = """\
start_date: 2024-01-01
end_date: 2024-01-01
contribution_schedule:
  type: monthly
  amount: 1000
  currency: EUR
"""
    with pytest.raises(ValidationError) as exc_info:
        parse_backtest_yaml(yaml_text)

    assert "start_date" in exc_info.value.details


def test_start_date_after_end_date_raises():
    """start_date > end_date is rejected."""
    yaml_text = """\
start_date: 2025-01-01
end_date: 2024-12-31
contribution_schedule:
  type: monthly
  amount: 1000
  currency: EUR
"""
    with pytest.raises(ValidationError) as exc_info:
        parse_backtest_yaml(yaml_text)

    assert "start_date" in exc_info.value.details


def test_dates_one_day_apart_accepted():
    """start_date one day before end_date is valid."""
    yaml_text = """\
start_date: 2024-01-01
end_date: 2024-01-02
contribution_schedule:
  type: monthly
  amount: 1000
  currency: EUR
"""
    config = parse_backtest_yaml(yaml_text)

    assert config.start_date == date(2024, 1, 1)
    assert config.end_date == date(2024, 1, 2)


# --- Monthly schedule validation ---


def test_monthly_amount_zero_raises():
    """amount == 0 is rejected."""
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: monthly
  amount: 0
  currency: EUR
"""
    with pytest.raises(ValidationError):
        parse_backtest_yaml(yaml_text)


def test_monthly_amount_negative_raises():
    """Negative amount is rejected."""
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: monthly
  amount: -500
  currency: EUR
"""
    with pytest.raises(ValidationError):
        parse_backtest_yaml(yaml_text)


def test_monthly_day_below_1_raises():
    """day_of_month < 1 is rejected."""
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: monthly
  amount: 1000
  currency: EUR
  day_of_month: 0
"""
    with pytest.raises(ValidationError):
        parse_backtest_yaml(yaml_text)


def test_monthly_day_above_28_raises():
    """day_of_month > 28 is rejected."""
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: monthly
  amount: 1000
  currency: EUR
  day_of_month: 29
"""
    with pytest.raises(ValidationError):
        parse_backtest_yaml(yaml_text)


def test_monthly_day_boundary_values():
    """day_of_month 1 and 28 are both valid."""
    for day in (1, 28):
        yaml_text = f"""\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: monthly
  amount: 1000
  currency: EUR
  day_of_month: {day}
"""
        config = parse_backtest_yaml(yaml_text)
        assert config.contribution_schedule.day_of_month == day


def test_monthly_invalid_currency_raises():
    """Non-3-letter currency is rejected."""
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: monthly
  amount: 1000
  currency: EURO
"""
    with pytest.raises(ValidationError):
        parse_backtest_yaml(yaml_text)


def test_monthly_numeric_currency_raises():
    """Currency with digits is rejected."""
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: monthly
  amount: 1000
  currency: EU1
"""
    with pytest.raises(ValidationError):
        parse_backtest_yaml(yaml_text)


# --- CSV schedule validation ---


def test_csv_empty_contributions_raises():
    """Empty contributions list is rejected."""
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: csv
  contributions: []
"""
    with pytest.raises(ValidationError):
        parse_backtest_yaml(yaml_text)


def test_csv_contribution_zero_amount_raises():
    """Contribution with amount == 0 is rejected."""
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: csv
  contributions:
    - date: 2020-01-15
      amount: 0
      currency: EUR
"""
    with pytest.raises(ValidationError):
        parse_backtest_yaml(yaml_text)


def test_csv_contribution_negative_amount_raises():
    """Contribution with negative amount is rejected."""
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: csv
  contributions:
    - date: 2020-01-15
      amount: -100
      currency: EUR
"""
    with pytest.raises(ValidationError):
        parse_backtest_yaml(yaml_text)


def test_csv_contribution_invalid_currency_raises():
    """Contribution with invalid currency is rejected."""
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: csv
  contributions:
    - date: 2020-01-15
      amount: 1000
      currency: XX
"""
    with pytest.raises(ValidationError):
        parse_backtest_yaml(yaml_text)


# --- Discriminated union ---


def test_invalid_schedule_type_raises():
    """Unknown schedule type is rejected."""
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  type: weekly
  amount: 1000
  currency: EUR
"""
    with pytest.raises(ValidationError):
        parse_backtest_yaml(yaml_text)


def test_missing_schedule_type_raises():
    """Schedule without type field is rejected."""
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
contribution_schedule:
  amount: 1000
  currency: EUR
"""
    with pytest.raises(ValidationError):
        parse_backtest_yaml(yaml_text)


# --- Missing required fields ---


def test_missing_start_date_raises():
    yaml_text = """\
end_date: 2024-12-31
contribution_schedule:
  type: monthly
  amount: 1000
  currency: EUR
"""
    with pytest.raises(ValidationError):
        parse_backtest_yaml(yaml_text)


def test_missing_end_date_raises():
    yaml_text = """\
start_date: 2020-01-01
contribution_schedule:
  type: monthly
  amount: 1000
  currency: EUR
"""
    with pytest.raises(ValidationError):
        parse_backtest_yaml(yaml_text)


def test_missing_contribution_schedule_raises():
    yaml_text = """\
start_date: 2020-01-01
end_date: 2024-12-31
"""
    with pytest.raises(ValidationError):
        parse_backtest_yaml(yaml_text)


# --- YAML syntax errors ---


def test_empty_yaml_raises():
    with pytest.raises(ValidationError) as exc_info:
        parse_backtest_yaml("")

    assert "empty" in exc_info.value.message.lower()


def test_whitespace_only_yaml_raises():
    with pytest.raises(ValidationError) as exc_info:
        parse_backtest_yaml("   \n\n  ")

    assert "empty" in exc_info.value.message.lower()


def test_invalid_yaml_syntax_raises():
    with pytest.raises(ValidationError) as exc_info:
        parse_backtest_yaml("key: [unclosed bracket")

    assert "YAML" in exc_info.value.message


def test_yaml_not_a_mapping_raises():
    with pytest.raises(ValidationError) as exc_info:
        parse_backtest_yaml("- just\n- a\n- list")

    assert "mapping" in exc_info.value.message


# --- Frozen model ---


def test_backtest_config_is_frozen():
    """BacktestConfig instances are immutable."""
    config = parse_backtest_yaml(MINIMAL_MONTHLY_YAML)

    with pytest.raises(PydanticValidationError):
        config.start_date = date(2021, 1, 1)  # type: ignore[misc]


def test_contribution_is_frozen():
    """Contribution instances are immutable."""
    c = Contribution(date=date(2020, 1, 15), amount=Decimal("1000"), currency="EUR")

    with pytest.raises(PydanticValidationError):
        c.amount = Decimal("2000")  # type: ignore[misc]


def test_monthly_schedule_is_frozen():
    """MonthlySchedule instances are immutable."""
    s = MonthlySchedule(amount=Decimal("1000"), currency="EUR", day_of_month=15)

    with pytest.raises(PydanticValidationError):
        s.amount = Decimal("2000")  # type: ignore[misc]
