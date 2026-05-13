import pytest
from fastapi import HTTPException

from src.api.v1.user_dicts import (
    _compact_select_fields_response,
    _extract_file_blob_from_value,
    _extract_row_ids_from_tables,
    _normalize_uuid_or_raise,
)


def test_extract_row_ids_from_tables_unique_and_ordered():
    # Dlya sebya: proverka scenariya "test extract row ids from tables unique and ordered".
    tables = [
        {
            "columns": [{"key": "uuid"}],
            "rows": [
                {"uuid": "{1}", "name": "a"},
                {"uuid": "{2}", "name": "b"},
            ],
        },
        {
            "columns": [{"key": "uuid"}],
            "rows": [
                {"uuid": "{2}", "name": "dup"},
                {"uuid": "{3}", "name": "c"},
            ],
        },
    ]
    assert _extract_row_ids_from_tables(tables) == ["{1}", "{2}", "{3}"]


def test_extract_row_ids_from_tables_ignores_rows_without_uuid():
    # Dlya sebya: proverka scenariya "test extract row ids from tables ignores rows without uuid".
    tables = [
        {
            "rows": [
                {"id": 1},
                {"uuid": ""},
                {"uuid": "   "},
                {"uuid": "{10}"},
            ]
        }
    ]
    assert _extract_row_ids_from_tables(tables) == ["{10}"]


def test_compact_select_fields_response_ignores_placeholder_row():
    # Dlya sebya: proverka scenariya "test compact select fields response ignores placeholder row".
    result = {
        "status": "ok",
        "report_code_name": "DONE",
        "description": "",
        "action_data": {
            "table_rows": [
                {
                    "table_columns": [
                        {"column_name": "", "column_type": [], "value": ["", 0, 0, False]}
                    ]
                }
            ]
        },
    }
    compact = _compact_select_fields_response(
        dict_name="demo",
        result=result,
        run_id=1,
    )
    assert compact["found_count"] == 0
    assert compact["rows"] == []
    assert compact["row_ids"] == []


def test_compact_select_fields_response_parses_values_by_column_type():
    # Dlya sebya: proverka scenariya "test compact select fields response parses values by column type".
    result = {
        "status": "ok",
        "report_code_name": "DONE",
        "description": "",
        "action_data": {
            "table_rows": [
                {
                    "table_columns": [
                        {
                            "column_name": "uuid",
                            "column_type": ["уникальный идентификатор"],
                            "value": ["{1}", 0, 0, False],
                        },
                        {
                            "column_name": "name",
                            "column_type": ["текстовое значение"],
                            "value": ["Иван", 0, 0, False],
                        },
                        {
                            "column_name": "is_active",
                            "column_type": ["флаг"],
                            "value": ["", 0, 0, False],
                        },
                        {
                            "column_name": "score",
                            "column_type": ["целочисленное значение"],
                            "value": ["", 0, 0, False],
                        },
                    ]
                }
            ]
        },
    }
    compact = _compact_select_fields_response(
        dict_name="demo",
        result=result,
        run_id=2,
    )
    assert compact["found_count"] == 1
    assert compact["row_ids"] == ["{1}"]
    assert compact["rows"] == [
        {"uuid": "{1}", "name": "Иван", "is_active": False, "score": 0}
    ]


def test_normalize_uuid_or_raise_accepts_uuid_and_braced_uuid():
    # Dlya sebya: proverka scenariya "test normalize uuid or raise accepts uuid and braced uuid".
    assert _normalize_uuid_or_raise("{123e4567-e89b-12d3-a456-426614174000}") == "{123e4567-e89b-12d3-a456-426614174000}"
    assert _normalize_uuid_or_raise("123e4567-e89b-12d3-a456-426614174000") == "{123e4567-e89b-12d3-a456-426614174000}"


def test_normalize_uuid_or_raise_rejects_placeholder():
    # Dlya sebya: proverka scenariya "test normalize uuid or raise rejects placeholder".
    with pytest.raises(HTTPException):
        _normalize_uuid_or_raise("ROW_KEEP_ID")


def test_extract_file_blob_from_value_supports_nested_value_payload():
    # Dlya sebya: proverka scenariya "test extract file blob from nested value payload".
    payload = {
        "filename": "nested.txt",
        "value": {"data_base64": "aGVsbG8="},  # hello
    }
    blob = _extract_file_blob_from_value(payload)
    assert blob["filename"] == "nested.txt"
    assert blob["bytes"] == b"hello"


def test_extract_file_blob_from_value_supports_plain_base64_string():
    # Dlya sebya: proverka scenariya "test extract file blob from plain base64 string".
    blob = _extract_file_blob_from_value("aGVsbG8=")
    assert blob["filename"] is None
    assert blob["bytes"] == b"hello"
