import pytest

from app.reviewer import review_sql
from app.schema import SchemaError

ALL = ["order_date", "quantity", "product", "amount"]


def ok(sql, cols=ALL):
    result = review_sql(sql, cols)
    assert result.passed, result.errors
    assert result.errors == ()
    assert result.formatted_sql
    return result


def fails(sql, cols=ALL, contains=""):
    result = review_sql(sql, cols)
    assert not result.passed
    assert any(contains in e for e in result.errors), result.errors
    return result


# ---------- pass cases ----------


@pytest.mark.parametrize(
    ("sql", "cols"),
    [
        # real SQL from the Phase 4 manual check
        (
            (
                "SELECT product, SUM(amount) AS total_sales FROM sales GROUP BY product "
                "ORDER BY total_sales DESC LIMIT 5"
            ),
            ["product", "amount"],
        ),
        ("SELECT COUNT(*) AS n FROM sales", ["amount"]),
        (
            (
                "SELECT product FROM sales WHERE amount > 100 GROUP BY product "
                "HAVING SUM(quantity) > 10"
            ),
            ["product", "amount", "quantity"],
        ),
        ("SELECT s.product, s.amount FROM sales AS s", ["product", "amount"]),
        ("SELECT sales.product FROM sales", ["product"]),
        (
            (
                "WITH t AS (SELECT product, SUM(amount) AS total FROM sales GROUP BY product) "
                "SELECT product, total FROM t ORDER BY total DESC"
            ),
            ["product", "amount"],
        ),
        ("SELECT product FROM sales UNION ALL SELECT product FROM sales", ["product"]),
        ("SELECT x.product FROM (SELECT product FROM sales) AS x", ["product"]),
        ("SELECT product FROM sales;", ["product"]),
        ("SELECT AMOUNT FROM SALES", ["amount"]),
        ("SELECT `amount` FROM `sales`", ["amount"]),
        (
            (
                "SELECT EXTRACT(YEAR FROM order_date) AS y, SUM(amount) AS total FROM sales "
                "WHERE order_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) GROUP BY y"
            ),
            ["order_date", "amount"],
        ),
    ],
)
def test_valid_queries_pass(sql, cols):
    ok(sql, cols)


def test_formatted_sql_is_multiline():
    result = ok("SELECT product, amount FROM sales WHERE amount > 1", ["product", "amount"])
    assert "\n" in result.formatted_sql


# ---------- fail cases: parse / statements / read-only ----------


@pytest.mark.parametrize(
    "sql", ["SELEC product FROM sales", "SELECT product FROM sales WHERE", "SELECT 'abc"]
)
def test_syntax_error(sql):
    result = fails(sql, contains="Syntax error")
    assert result.formatted_sql is None


@pytest.mark.parametrize("sql", ["", "   ", None])
def test_empty_sql(sql):
    fails(sql, contains="No SQL to review")


def test_two_statements():
    fails("SELECT amount FROM sales; SELECT product FROM sales", contains="exactly one statement")


@pytest.mark.parametrize(
    ("sql", "kind"),
    [
        ("DROP TABLE sales", "DROP"),
        ("DELETE FROM sales WHERE amount > 0", "DELETE"),
        ("INSERT INTO sales (amount) VALUES (1)", "INSERT"),
        ("UPDATE sales SET amount = 0 WHERE TRUE", "UPDATE"),
        ("hello world", ""),
    ],
)
def test_non_select_rejected(sql, kind):
    fails(sql, contains=f"Only SELECT queries are allowed (got {kind}")


# ---------- fail cases: tables / star / columns ----------


def test_unknown_table():
    fails("SELECT amount FROM customers", contains="Unknown table: customers")


def test_unknown_table_in_subquery():
    fails(
        "SELECT amount FROM sales WHERE product IN (SELECT name FROM products)",
        contains="Unknown table: products",
    )


def test_qualified_sales_table_rejected():
    fails("SELECT amount FROM `proj.ds.sales`", contains="plain table name")


@pytest.mark.parametrize("sql", ["SELECT * FROM sales", "SELECT s.* FROM sales AS s"])
def test_star_rejected(sql):
    fails(sql, contains="SELECT * is not allowed")


def test_unselected_schema_column():
    fails(
        "SELECT product, quantity FROM sales", ["product"], contains="Column not selected: quantity"
    )


def test_unknown_column():
    fails("SELECT region FROM sales", ["product"], contains="Column not allowed: region")


def test_bad_qualifier():
    fails("SELECT other.amount FROM sales", ["amount"], contains="Unknown table qualifier")


def test_alias_cannot_hide_unselected_column():
    fails(
        "SELECT quantity AS quantity FROM sales",
        ["amount"],
        contains="Alias reuses a column that wasn't selected: quantity",
    )


def test_all_errors_reported_together():
    result = review_sql("SELECT *, region, quantity FROM customers", ["amount"])
    assert not result.passed
    joined = " | ".join(result.errors)
    for expected in ("Unknown table", "SELECT *", "region", "quantity"):
        assert expected in joined
    assert result.formatted_sql is not None


def test_invalid_selection_raises():
    with pytest.raises(SchemaError):
        review_sql("SELECT amount FROM sales", ["region"])
