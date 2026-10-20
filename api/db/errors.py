from asyncpg import UniqueViolationError
from sqlalchemy.exc import IntegrityError


def is_unique_violation(error: IntegrityError, *, constraint: str) -> bool:
    cause = error.orig.__cause__ if error.orig is not None else None
    return isinstance(cause, UniqueViolationError) and cause.as_dict().get("constraint_name") == constraint
