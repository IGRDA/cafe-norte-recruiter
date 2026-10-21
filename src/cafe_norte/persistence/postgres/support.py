"""The plumbing every Postgres repository shares: the pool, the transaction, the one place
psycopg errors become ``ServiceError`` codes, and the row fetchers."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import psycopg
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from cafe_norte.errors import ServiceError
from cafe_norte.persistence.contracts import Transaction

Connection = AsyncConnection[DictRow]
Connect = Callable[[], AbstractAsyncContextManager[Connection]]
Params = dict[str, Any] | tuple[Any, ...]


def make_pool(
    dsn: str,
    *,
    pool_size: int,
    checkout_seconds: float,
    statement_seconds: float,
    lock_seconds: float,
) -> AsyncConnectionPool[Connection]:
    """Closed until ``open``. Timeouts are connection options, so they cost no round trip;
    ``TimeZone=UTC`` makes every ``timestamptz`` an aware UTC datetime on the way back."""
    options = (
        f"-c statement_timeout={int(statement_seconds * 1000)} "
        f"-c lock_timeout={int(lock_seconds * 1000)} "
        "-c idle_in_transaction_session_timeout=10000 -c TimeZone=UTC"
    )
    return AsyncConnectionPool(
        dsn,
        connection_class=Connection,
        kwargs={"row_factory": dict_row, "options": options},
        min_size=1,
        max_size=pool_size,
        open=False,
        timeout=checkout_seconds,
    )


class PostgresTransaction:
    """One connection, one database transaction. ``commit`` and ``rollback`` map straight onto
    the connection because callers may call them in the middle of the block."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.committed = False

    async def commit(self) -> None:
        await self.connection.commit()
        self.committed = True

    async def rollback(self) -> None:
        await self.connection.rollback()


def connection(tx: Transaction) -> Connection:
    if not isinstance(tx, PostgresTransaction):
        raise TypeError("PostgresStore repositories need a PostgresTransaction")
    return tx.connection


@asynccontextmanager
async def translating() -> AsyncIterator[None]:
    """psycopg errors become ``ServiceError`` codes; a ``ServiceError`` passes through."""
    try:
        yield
    except ServiceError:
        raise
    except psycopg.errors.UniqueViolation as error:
        raise ServiceError(f"unique: {error.diag.constraint_name}", code="conflict") from error
    except psycopg.errors.ForeignKeyViolation as error:
        raise ServiceError(f"missing: {error.diag.constraint_name}", code="not_found") from error
    except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled) as error:
        raise ServiceError("database timeout", code="timeout") from error
    except PoolTimeout as error:
        raise ServiceError("no database connection free", code="busy") from error
    except psycopg.OperationalError as error:
        raise ServiceError("database unavailable", code="provider_unavailable") from error


@asynccontextmanager
async def reading(connect: Connect) -> AsyncIterator[Connection]:
    """A connection for a read-only method: its implicit transaction ends with the block."""
    async with translating(), connect() as conn:
        yield conn


@asynccontextmanager
async def writing(connect: Connect) -> AsyncIterator[Connection]:
    """A connection for a method that writes without a caller's transaction: committed on a
    clean exit, rolled back by the pool otherwise."""
    async with translating(), connect() as conn:
        yield conn
        await conn.commit()


async def fetch_all(conn: Connection, sql: str, params: Params = ()) -> list[DictRow]:
    return await (await conn.execute(sql, params)).fetchall()


async def fetch_one(conn: Connection, sql: str, params: Params = ()) -> DictRow | None:
    return await (await conn.execute(sql, params)).fetchone()
