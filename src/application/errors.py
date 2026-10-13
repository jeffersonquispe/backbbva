"""Application-facing business error categories and shared domain base."""

from src.domain import (
    ConflictError,
    DomainException,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)

__all__ = [
    "ConflictError",
    "DomainException",
    "ForbiddenError",
    "NotFoundError",
    "RetryableError",
    "ValidationError",
]


class RetryableError(DomainException):
    """Transient business boundary failure that a worker may retry."""
