import datetime
from decimal import Decimal

import pytest

from app.core.errors import DataMissingError
from app.domain.fx import FxProvider, convert

DATE = datetime.date(2024, 1, 15)


def make_fx_provider(rates: dict[tuple[str, datetime.date], Decimal]) -> FxProvider:
    def provider(pair: str, d: datetime.date) -> Decimal | None:
        return rates.get((pair, d))

    return provider


# --- Same-currency (no-op) ---


def test_convert_same_currency_returns_amount_unchanged() -> None:
    provider = make_fx_provider({})
    result = convert(Decimal("100.50"), "EUR", "EUR", DATE, provider)
    assert result == Decimal("100.50")


def test_convert_same_currency_case_insensitive() -> None:
    provider = make_fx_provider({})
    result = convert(Decimal("100"), "eur", "EUR", DATE, provider)
    assert result == Decimal("100")


# --- Direct pair lookup ---


def test_convert_direct_pair_found() -> None:
    provider = make_fx_provider({("USD/EUR", DATE): Decimal("0.92")})
    result = convert(Decimal("100"), "USD", "EUR", DATE, provider)
    assert result == Decimal("100") * Decimal("0.92")


def test_convert_preserves_decimal_precision() -> None:
    provider = make_fx_provider({("USD/EUR", DATE): Decimal("0.123456789")})
    result = convert(Decimal("1"), "USD", "EUR", DATE, provider)
    assert result == Decimal("0.123456789")


# --- Inverse pair fallback ---


def test_convert_inverse_pair_fallback() -> None:
    provider = make_fx_provider({("EUR/USD", DATE): Decimal("1.0870")})
    result = convert(Decimal("100"), "USD", "EUR", DATE, provider)
    assert result == Decimal("100") / Decimal("1.0870")


def test_convert_direct_pair_preferred_over_inverse() -> None:
    provider = make_fx_provider(
        {
            ("USD/EUR", DATE): Decimal("0.92"),
            ("EUR/USD", DATE): Decimal("1.0870"),
        }
    )
    result = convert(Decimal("100"), "USD", "EUR", DATE, provider)
    assert result == Decimal("100") * Decimal("0.92")


# --- Error case ---


def test_convert_raises_data_missing_error_when_no_rate_found() -> None:
    provider = make_fx_provider({})
    with pytest.raises(DataMissingError) as exc_info:
        convert(Decimal("100"), "USD", "EUR", DATE, provider)
    assert "USD/EUR" in exc_info.value.message
    assert str(DATE) in exc_info.value.message


def test_convert_error_details_contain_both_pairs() -> None:
    provider = make_fx_provider({})
    with pytest.raises(DataMissingError) as exc_info:
        convert(Decimal("100"), "USD", "EUR", DATE, provider)
    assert "USD/EUR" in str(exc_info.value.details)
    assert "EUR/USD" in str(exc_info.value.details)


# --- Currency normalization ---


def test_convert_normalizes_currency_to_uppercase() -> None:
    provider = make_fx_provider({("USD/EUR", DATE): Decimal("0.92")})
    result = convert(Decimal("100"), "usd", "eur", DATE, provider)
    assert result == Decimal("100") * Decimal("0.92")


# --- Edge cases ---


def test_convert_zero_amount() -> None:
    provider = make_fx_provider({("USD/EUR", DATE): Decimal("0.92")})
    result = convert(Decimal("0"), "USD", "EUR", DATE, provider)
    assert result == Decimal("0")


# --- Determinism ---


def test_convert_is_deterministic() -> None:
    provider = make_fx_provider({("USD/EUR", DATE): Decimal("0.92")})
    result1 = convert(Decimal("100"), "USD", "EUR", DATE, provider)
    result2 = convert(Decimal("100"), "USD", "EUR", DATE, provider)
    assert result1 == result2
