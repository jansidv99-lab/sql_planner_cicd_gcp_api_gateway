import pytest

from app.schema import COLUMN_NAMES, TABLE_NAME, SchemaError, schema_for_prompt, validate_selection


def test_schema_has_expected_columns():
    assert TABLE_NAME == "sales"
    assert COLUMN_NAMES == ("order_date", "quantity", "product", "amount")


def test_valid_subset_accepted():
    assert validate_selection(["product", "amount"]) == ("product", "amount")


def test_result_in_schema_order():
    assert validate_selection(["amount", "order_date"]) == ("order_date", "amount")


def test_duplicates_removed():
    assert validate_selection(["amount", "amount", "product"]) == ("product", "amount")


def test_empty_rejected():
    with pytest.raises(SchemaError, match="at least one"):
        validate_selection([])


def test_unknown_column_rejected():
    with pytest.raises(SchemaError, match="region"):
        validate_selection(["amount", "region"])


def test_wrong_case_rejected():
    with pytest.raises(SchemaError, match="ORDER_DATE"):
        validate_selection(["ORDER_DATE"])


def test_prompt_includes_selected_columns_with_types():
    text = schema_for_prompt(["order_date", "amount"])
    assert "Table: sales" in text
    assert "- order_date DATE" in text
    assert "- amount NUMERIC" in text


def test_prompt_excludes_unselected_columns():
    text = schema_for_prompt(["amount"])
    assert "quantity" not in text
    assert "product" not in text
    assert "order_date" not in text


def test_prompt_rejects_invalid_selection():
    with pytest.raises(SchemaError):
        schema_for_prompt(["region"])
