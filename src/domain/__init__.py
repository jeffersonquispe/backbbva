class DomainException(Exception):
    """Base for expected business errors shared across application layers."""


class ValidationError(DomainException, ValueError):
    """Invalid business input."""


class NotFoundError(DomainException):
    """Requested business resource does not exist."""


class ConflictError(DomainException):
    """Requested operation conflicts with current business state."""


class ForbiddenError(DomainException):
    """Business operation is forbidden."""
