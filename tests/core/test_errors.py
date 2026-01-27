import pytest

from app.core.errors import DataMissingError, PlumblineError, PolicyError, ValidationError


def test_plumbline_error_stores_message() -> None:
    err = PlumblineError("Something went wrong")
    assert err.message == "Something went wrong"
    assert err.details is None
    assert str(err) == "Something went wrong"


def test_plumbline_error_stores_details() -> None:
    err = PlumblineError("Error occurred", details="Additional context")
    assert err.message == "Error occurred"
    assert err.details == "Additional context"


def test_validation_error_is_plumbline_error() -> None:
    err = ValidationError("Invalid input")
    assert isinstance(err, PlumblineError)
    assert isinstance(err, ValidationError)


def test_data_missing_error_is_plumbline_error() -> None:
    err = DataMissingError("Data not found", details="Ticker XYZ")
    assert isinstance(err, PlumblineError)
    assert isinstance(err, DataMissingError)
    assert err.details == "Ticker XYZ"


def test_policy_error_is_plumbline_error() -> None:
    err = PolicyError("Policy violated")
    assert isinstance(err, PlumblineError)
    assert isinstance(err, PolicyError)


def test_errors_can_be_raised_and_caught() -> None:
    with pytest.raises(ValidationError) as exc_info:
        raise ValidationError("Bad value", details="Expected int, got str")
    assert exc_info.value.message == "Bad value"
    assert exc_info.value.details == "Expected int, got str"


def test_errors_caught_as_base_class() -> None:
    errors = [
        ValidationError("validation"),
        DataMissingError("missing"),
        PolicyError("policy"),
    ]
    for err in errors:
        with pytest.raises(PlumblineError):
            raise err
