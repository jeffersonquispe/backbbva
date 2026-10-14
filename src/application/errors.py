"""Application-facing business error categories and shared domain base."""

from src.domain import (
    ConflictError,
    DomainException,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)


class ConfigurationWriteConflict(ConflictError):
    """A concurrent configuration change invalidated this write."""


__all__ = [
    "ConflictError",
    "ConfigurationWriteConflict",
    "DomainException",
    "ForbiddenError",
    "NotFoundError",
    "RetryableError",
    "ValidationError",
]


class RetryableError(DomainException):
    """Transient business boundary failure that a worker may retry."""
