from asyncpg import PostgresError, UniqueViolationError
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError


def is_unique_violation(error: IntegrityError, *, constraint: str) -> bool:
    cause = error.orig.__cause__ if error.orig is not None else None
    return isinstance(cause, UniqueViolationError) and cause.as_dict().get("constraint_name") == constraint


def is_database_unavailable(error: SQLAlchemyError | PostgresError) -> bool:
    if isinstance(error, PoolTimeoutError):
        return True
    if isinstance(error, DBAPIError):
        if error.connection_invalidated:
            return True
        cause = error.orig.__cause__ if error.orig is not None else None
    else:
        cause = error
    if not isinstance(cause, PostgresError):
        return False
    # Connection failures, resource exhaustion, shutdown/query cancellation and lock timeout.
    code = cause.as_dict().get("sqlstate")
    return isinstance(code, str) and (code[:2] in {"08", "53", "57"} or code == "55P03")
