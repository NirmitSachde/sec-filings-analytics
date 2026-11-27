"""Small fakes for SQLAlchemy sessions used by the API route tests.

The routes call ``get_session()`` directly, so tests patch that name in each route
module with a ``FakeSession``. Every ``session.query(...)`` call takes the next
``FakeQuery`` from a queue, which lets a test script the exact results the route sees
and then inspect the filters, ordering and limits the route applied.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects import postgresql


def render(clause: Any) -> str:
    """Render a SQLAlchemy clause as Postgres SQL with literal values inlined."""
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class FakeQuery:
    def __init__(
        self,
        all_result: list[Any] | None = None,
        *,
        first: Any = None,
        scalar: Any = None,
    ) -> None:
        self.entities: tuple[Any, ...] = ()
        self._all = list(all_result or [])
        self._first = first
        self._scalar = scalar
        self.filters: list[Any] = []
        self.order_bys: list[Any] = []
        self.group_bys: list[Any] = []
        self.havings: list[Any] = []
        self.limit_value: int | None = None
        self.distinct_called = False

    # Chainable builders -------------------------------------------------
    def filter(self, *criteria: Any) -> FakeQuery:
        self.filters.extend(criteria)
        return self

    def order_by(self, *clauses: Any) -> FakeQuery:
        self.order_bys.extend(clauses)
        return self

    def group_by(self, *clauses: Any) -> FakeQuery:
        self.group_bys.extend(clauses)
        return self

    def having(self, *criteria: Any) -> FakeQuery:
        self.havings.extend(criteria)
        return self

    def distinct(self) -> FakeQuery:
        self.distinct_called = True
        return self

    def limit(self, n: int) -> FakeQuery:
        self.limit_value = n
        return self

    # Terminal calls -----------------------------------------------------
    def all(self) -> list[Any]:
        return list(self._all)

    def first(self) -> Any:
        return self._first

    def scalar(self) -> Any:
        return self._scalar

    # Helpers for assertions ---------------------------------------------
    def rendered_filters(self) -> list[str]:
        return [render(f) for f in self.filters]

    def rendered_order_bys(self) -> list[str]:
        return [render(o) for o in self.order_bys]


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchall(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    def __init__(
        self,
        queries: list[FakeQuery] | None = None,
        execute_rows: list[Any] | None = None,
    ) -> None:
        self._pending = list(queries or [])
        self.queries: list[FakeQuery] = []
        self._execute_rows = list(execute_rows or [])
        self.executed: list[tuple[Any, Any]] = []
        self.closed = False

    def query(self, *entities: Any) -> FakeQuery:
        if not self._pending:
            raise AssertionError(f"Unexpected extra session.query({entities!r}) call")
        q = self._pending.pop(0)
        q.entities = entities
        self.queries.append(q)
        return q

    def execute(self, statement: Any, params: Any = None) -> FakeResult:
        self.executed.append((statement, params))
        return FakeResult(self._execute_rows)

    def close(self) -> None:
        self.closed = True
