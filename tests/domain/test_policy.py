import hashlib
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ValidationError
from app.domain.policy import (
    ConstraintsConfig,
    CostsConfig,
    RebalancingConfig,
    parse_policy_yaml,
)

MINIMAL_YAML = """\
base_currency: EUR
buckets:
  core:
    targets:
      IWDA.AS: 0.60
      EIMI.AS: 0.25
      IUSN.AS: 0.15
"""

FULL_YAML = """\
base_currency: EUR
buckets:
  core:
    targets:
      IWDA.AS: 0.60
      EIMI.AS: 0.25
      IUSN.AS: 0.15
  satellite:
    targets:
      AAPL: 0.40
      GOOGL: 0.35
      TSLA: 0.25
constraints:
  min_trade_value: 50.00
  max_position_weight: 0.25
  no_sell: true
rebalancing:
  drift_soft: 0.03
  drift_hard: 0.10
costs:
  commission_fixed: 1.00
  fx_spread_bps: 10
"""


# ---------------------------------------------------------------------------
# A. Valid parsing (happy path)
# ---------------------------------------------------------------------------


def test_parse_minimal_policy() -> None:
    policy = parse_policy_yaml(MINIMAL_YAML)

    assert policy.base_currency == "EUR"
    assert len(policy.buckets.core.targets) == 3
    assert policy.buckets.satellite is None

    # Defaults
    assert policy.constraints == ConstraintsConfig()
    assert policy.rebalancing == RebalancingConfig()
    assert policy.costs == CostsConfig()


def test_parse_full_policy() -> None:
    policy = parse_policy_yaml(FULL_YAML)

    assert policy.base_currency == "EUR"

    # Core
    assert policy.buckets.core.targets["IWDA.AS"] == Decimal("0.6")
    assert policy.buckets.core.targets["EIMI.AS"] == Decimal("0.25")
    assert policy.buckets.core.targets["IUSN.AS"] == Decimal("0.15")

    # Satellite
    assert policy.buckets.satellite is not None
    assert policy.buckets.satellite.targets["AAPL"] == Decimal("0.4")
    assert policy.buckets.satellite.targets["GOOGL"] == Decimal("0.35")
    assert policy.buckets.satellite.targets["TSLA"] == Decimal("0.25")

    # Constraints
    assert policy.constraints.min_trade_value == Decimal("50")
    assert policy.constraints.max_position_weight == Decimal("0.25")
    assert policy.constraints.no_sell is True

    # Rebalancing
    assert policy.rebalancing.drift_soft == Decimal("0.03")
    assert policy.rebalancing.drift_hard == Decimal("0.1")

    # Costs
    assert policy.costs.commission_fixed == Decimal("1")
    assert policy.costs.fx_spread_bps == 10


def test_parse_core_only_no_satellite() -> None:
    policy = parse_policy_yaml(MINIMAL_YAML)
    assert policy.buckets.satellite is None


def test_parse_with_satellite() -> None:
    policy = parse_policy_yaml(FULL_YAML)
    assert policy.buckets.satellite is not None
    assert len(policy.buckets.satellite.targets) == 3


def test_policy_hash_is_sha256_of_raw_text() -> None:
    stripped = MINIMAL_YAML.strip()
    expected = hashlib.sha256(stripped.encode("utf-8")).hexdigest()
    policy = parse_policy_yaml(MINIMAL_YAML)
    assert policy.policy_hash == expected


def test_policy_hash_differs_for_different_whitespace() -> None:
    yaml_a = "base_currency: EUR\nbuckets:\n  core:\n    targets:\n      A: 1.0\n"
    yaml_b = "base_currency:  EUR\nbuckets:\n  core:\n    targets:\n      A: 1.0\n"
    policy_a = parse_policy_yaml(yaml_a)
    policy_b = parse_policy_yaml(yaml_b)
    assert policy_a.policy_hash != policy_b.policy_hash


def test_tickers_normalized_to_uppercase() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      iwda.as: 0.60
      Eimi.As: 0.25
      IUSN.AS: 0.15
"""
    policy = parse_policy_yaml(yaml_text)
    assert all(ticker == ticker.upper() for ticker in policy.buckets.core.targets)
    assert "IWDA.AS" in policy.buckets.core.targets
    assert "EIMI.AS" in policy.buckets.core.targets


def test_tickers_sorted_deterministically() -> None:
    policy = parse_policy_yaml(MINIMAL_YAML)
    tickers = list(policy.buckets.core.targets.keys())
    assert tickers == sorted(tickers)


def test_base_currency_normalized_to_uppercase() -> None:
    yaml_text = """\
base_currency: eur
buckets:
  core:
    targets:
      A: 1.0
"""
    policy = parse_policy_yaml(yaml_text)
    assert policy.base_currency == "EUR"


def test_parse_is_deterministic() -> None:
    policy_a = parse_policy_yaml(FULL_YAML)
    policy_b = parse_policy_yaml(FULL_YAML)
    assert policy_a == policy_b
    assert policy_a.policy_hash == policy_b.policy_hash


# ---------------------------------------------------------------------------
# B. Invalid weight sums
# ---------------------------------------------------------------------------


def test_core_weights_sum_below_one_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      A: 0.50
      B: 0.30
"""
    with pytest.raises(ValidationError) as exc_info:
        parse_policy_yaml(yaml_text)
    assert "sum to 1.0" in exc_info.value.message or "sum to 1.0" in (exc_info.value.details or "")


def test_core_weights_sum_above_one_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      A: 0.60
      B: 0.50
"""
    with pytest.raises(ValidationError) as exc_info:
        parse_policy_yaml(yaml_text)
    assert "sum to 1.0" in exc_info.value.message or "sum to 1.0" in (exc_info.value.details or "")


def test_satellite_weights_sum_not_one_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      A: 1.0
  satellite:
    targets:
      X: 0.30
      Y: 0.20
"""
    with pytest.raises(ValidationError) as exc_info:
        parse_policy_yaml(yaml_text)
    assert "Satellite" in (exc_info.value.details or "")


def test_core_weights_within_tolerance_accepted() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      A: 0.3334
      B: 0.3333
      C: 0.3333
"""
    policy = parse_policy_yaml(yaml_text)
    total = sum(policy.buckets.core.targets.values())
    assert abs(total - Decimal("1")) <= Decimal("0.001")


def test_core_weights_outside_tolerance_rejected() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      A: 0.50
      B: 0.502
"""
    with pytest.raises(ValidationError):
        parse_policy_yaml(yaml_text)


# ---------------------------------------------------------------------------
# C. Missing required fields
# ---------------------------------------------------------------------------


def test_missing_base_currency_raises() -> None:
    yaml_text = """\
buckets:
  core:
    targets:
      A: 1.0
"""
    with pytest.raises(ValidationError) as exc_info:
        parse_policy_yaml(yaml_text)
    assert "base_currency" in (exc_info.value.details or "")


def test_missing_buckets_raises() -> None:
    yaml_text = """\
base_currency: EUR
"""
    with pytest.raises(ValidationError) as exc_info:
        parse_policy_yaml(yaml_text)
    assert "buckets" in (exc_info.value.details or "")


def test_missing_core_bucket_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  satellite:
    targets:
      X: 1.0
"""
    with pytest.raises(ValidationError) as exc_info:
        parse_policy_yaml(yaml_text)
    assert "core" in (exc_info.value.details or "")


def test_missing_core_targets_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core: {}
"""
    with pytest.raises(ValidationError) as exc_info:
        parse_policy_yaml(yaml_text)
    assert "targets" in (exc_info.value.details or "")


def test_empty_core_targets_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets: {}
"""
    with pytest.raises(ValidationError) as exc_info:
        parse_policy_yaml(yaml_text)
    assert "empty" in (exc_info.value.details or "")


# ---------------------------------------------------------------------------
# D. Invalid field values
# ---------------------------------------------------------------------------


def test_invalid_base_currency_too_long() -> None:
    yaml_text = """\
base_currency: EURO
buckets:
  core:
    targets:
      A: 1.0
"""
    with pytest.raises(ValidationError):
        parse_policy_yaml(yaml_text)


def test_invalid_base_currency_numeric() -> None:
    yaml_text = """\
base_currency: "123"
buckets:
  core:
    targets:
      A: 1.0
"""
    with pytest.raises(ValidationError):
        parse_policy_yaml(yaml_text)


def test_negative_weight_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      A: -0.1
      B: 1.1
"""
    with pytest.raises(ValidationError):
        parse_policy_yaml(yaml_text)


def test_zero_weight_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      A: 0
      B: 1.0
"""
    with pytest.raises(ValidationError):
        parse_policy_yaml(yaml_text)


def test_weight_above_one_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      A: 1.5
"""
    with pytest.raises(ValidationError):
        parse_policy_yaml(yaml_text)


def test_min_trade_value_negative_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      A: 1.0
constraints:
  min_trade_value: -10
"""
    with pytest.raises(ValidationError):
        parse_policy_yaml(yaml_text)


def test_max_position_weight_zero_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      A: 1.0
constraints:
  max_position_weight: 0
"""
    with pytest.raises(ValidationError):
        parse_policy_yaml(yaml_text)


def test_max_position_weight_above_one_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      A: 1.0
constraints:
  max_position_weight: 1.5
"""
    with pytest.raises(ValidationError):
        parse_policy_yaml(yaml_text)


def test_drift_soft_exceeds_hard_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      A: 1.0
rebalancing:
  drift_soft: 0.10
  drift_hard: 0.03
"""
    with pytest.raises(ValidationError):
        parse_policy_yaml(yaml_text)


def test_commission_fixed_negative_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      A: 1.0
costs:
  commission_fixed: -1
"""
    with pytest.raises(ValidationError):
        parse_policy_yaml(yaml_text)


def test_fx_spread_bps_negative_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      A: 1.0
costs:
  fx_spread_bps: -5
"""
    with pytest.raises(ValidationError):
        parse_policy_yaml(yaml_text)


# ---------------------------------------------------------------------------
# E. YAML syntax errors
# ---------------------------------------------------------------------------


def test_empty_yaml_raises() -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_policy_yaml("")
    assert "empty" in exc_info.value.message.lower()


def test_whitespace_only_yaml_raises() -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_policy_yaml("   \n\n  \t  ")
    assert "empty" in exc_info.value.message.lower()


def test_invalid_yaml_syntax_raises() -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_policy_yaml(":\n  - :\n  bad: [yaml: {")
    assert "YAML" in exc_info.value.message


def test_yaml_that_is_not_a_mapping_raises() -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_policy_yaml("- item1\n- item2\n")
    assert "mapping" in exc_info.value.message.lower()


# ---------------------------------------------------------------------------
# F. Cross-bucket validation
# ---------------------------------------------------------------------------


def test_ticker_overlap_between_core_and_satellite_raises() -> None:
    yaml_text = """\
base_currency: EUR
buckets:
  core:
    targets:
      AAPL: 0.60
      GOOGL: 0.40
  satellite:
    targets:
      AAPL: 0.50
      TSLA: 0.50
"""
    with pytest.raises(ValidationError) as exc_info:
        parse_policy_yaml(yaml_text)
    assert "AAPL" in (exc_info.value.details or "")


# ---------------------------------------------------------------------------
# G. Frozen model
# ---------------------------------------------------------------------------


def test_policy_config_is_frozen() -> None:
    policy = parse_policy_yaml(MINIMAL_YAML)
    with pytest.raises(PydanticValidationError):
        policy.base_currency = "USD"  # type: ignore[misc]
