"""Chain step 3 (gate): deterministic checks that the SQL parses and stays inside the schema.

No LLM is used. Checks:
1. parses as BigQuery SQL          4. only the `sales` table (or CTEs defined in the query)
2. exactly one statement           5. no `*` wildcard except COUNT(*)
3. read-only query (SELECT/UNION)  6. only the selected columns (plus aliases defined in the query)
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.schema import COLUMN_NAMES, TABLE_NAME, validate_selection

DIALECT = "bigquery"


@dataclass(frozen=True)
class ReviewResult:
    passed: bool
    errors: tuple[str, ...]  # empty when passed
    formatted_sql: str | None  # pretty-printed SQL when it parsed, else None


def _fail(*errors: str) -> ReviewResult:
    return ReviewResult(passed=False, errors=errors, formatted_sql=None)


def _check_tables(stmt: exp.Expression, cte_names: set[str]) -> tuple[list[str], set[str]]:
    """Return (errors, aliases of the sales table)."""
    errors: list[str] = []
    sales_aliases: set[str] = set()
    for table in stmt.find_all(exp.Table):
        name = table.name.lower()
        qualified = bool(table.args.get("db") or table.args.get("catalog"))
        if name == TABLE_NAME and not qualified:
            if table.alias:
                sales_aliases.add(table.alias.lower())
        elif name in cte_names and not qualified:
            continue
        elif name == TABLE_NAME:
            errors.append(f"Use the plain table name `{TABLE_NAME}` (got {table.sql(DIALECT)})")
        else:
            errors.append(f"Unknown table: {table.sql(DIALECT)}")
    return errors, sales_aliases


def _check_stars(stmt: exp.Expression) -> list[str]:
    for star in stmt.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            return ["SELECT * is not allowed; list the columns explicitly"]
    return []


def _check_columns(stmt: exp.Expression, selected: set[str], qualifiers: set[str]) -> list[str]:
    errors: list[str] = []
    unselected = set(COLUMN_NAMES) - selected

    aliases: set[str] = set()
    for alias_node in stmt.find_all(exp.Alias):
        alias = alias_node.alias.lower()
        if alias in unselected:
            # Otherwise `SELECT quantity AS quantity` would sneak an unselected column through.
            errors.append(f"Alias reuses a column that wasn't selected: {alias}")
        else:
            aliases.add(alias)

    for col in stmt.find_all(exp.Column):
        if isinstance(col.this, exp.Star):
            continue  # reported by the star check
        table = col.table.lower()
        if table and table not in qualifiers:
            errors.append(f"Unknown table qualifier: {col.sql(DIALECT)}")
        name = col.name.lower()
        if name in selected or name in aliases:
            continue
        if name in unselected:
            errors.append(f"Column not selected: {name}")
        else:
            errors.append(f"Column not allowed: {name}")
    return errors


def review_sql(sql: str, selected_columns: Iterable[str]) -> ReviewResult:
    """Run all checks. Parse failures stop early; otherwise every problem is reported."""
    selected = {c.lower() for c in validate_selection(selected_columns)}

    if not (sql or "").strip():
        return _fail("No SQL to review")

    # Check 1: parses
    try:
        statements = [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]
    except SqlglotError as err:
        return _fail(f"Syntax error: {str(err).splitlines()[0]}")

    # Check 2: exactly one statement
    if len(statements) != 1:
        return _fail(f"Expected exactly one statement, found {len(statements)}")
    stmt = statements[0]
    formatted = stmt.sql(dialect=DIALECT, pretty=True)

    # Check 3: read-only query
    if not isinstance(stmt, exp.Query):
        kind = stmt.key.upper()
        return ReviewResult(False, (f"Only SELECT queries are allowed (got {kind})",), formatted)

    cte_names = {cte.alias.lower() for cte in stmt.find_all(exp.CTE) if cte.alias}
    subquery_aliases = {sq.alias.lower() for sq in stmt.find_all(exp.Subquery) if sq.alias}

    errors: list[str] = []
    # Check 4: tables
    table_errors, sales_aliases = _check_tables(stmt, cte_names)
    errors += table_errors
    # Check 5: no * wildcard
    errors += _check_stars(stmt)
    # Check 6: columns
    qualifiers = {TABLE_NAME} | sales_aliases | cte_names | subquery_aliases
    errors += _check_columns(stmt, selected, qualifiers)

    unique = tuple(dict.fromkeys(errors))  # de-duplicate, keep order
    return ReviewResult(passed=not unique, errors=unique, formatted_sql=formatted)
