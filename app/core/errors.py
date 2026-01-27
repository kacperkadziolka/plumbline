class PlumblineError(Exception):
    """Base exception for all Plumbline errors."""

    def __init__(self, message: str, details: str | None = None) -> None:
        self.message = message
        self.details = details
        super().__init__(message)


class ValidationError(PlumblineError):
    """Raised when input validation fails (e.g., invalid policy rules, bad parameters)."""

    pass


class DataMissingError(PlumblineError):
    """Raised when required data is not found (e.g., missing price data, unknown ticker)."""

    pass


class PolicyError(PlumblineError):
    """Raised when policy evaluation fails (e.g., conflicting constraints, infeasible allocation)."""

    pass
