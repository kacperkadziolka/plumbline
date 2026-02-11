from collections.abc import Callable
from datetime import date
from decimal import Decimal

from app.core.errors import DataMissingError

FxProvider = Callable[[str, date], Decimal | None]


def convert(
    amount: Decimal,
    from_ccy: str,
    to_ccy: str,
    date: date,
    fx_provider: FxProvider,
) -> Decimal:
    """Convert an amount between currencies using the given FX provider.

    Pair convention: "XXX/YYY" with rate R means 1 XXX = R YYY.
    Tries the direct pair first, then the inverse pair as fallback.
    """
    from_ccy = from_ccy.upper()
    to_ccy = to_ccy.upper()

    if from_ccy == to_ccy:
        return amount

    # Direct lookup: from_ccy/to_ccy
    direct_pair = f"{from_ccy}/{to_ccy}"
    rate = fx_provider(direct_pair, date)
    if rate is not None:
        return amount * rate

    # Inverse fallback: to_ccy/from_ccy
    inverse_pair = f"{to_ccy}/{from_ccy}"
    rate = fx_provider(inverse_pair, date)
    if rate is not None:
        return amount / rate

    raise DataMissingError(
        message=f"No FX rate found for {from_ccy}/{to_ccy} on {date}",
        details=f"Looked up '{direct_pair}' and '{inverse_pair}', neither found",
    )
