import xml.etree.ElementTree as ET

import pytest

from src.services import user_dict_xml


def test_normalize_column_type_accepts_key_and_label():
    # Dlya sebya: proverka scenariya "test normalize column type accepts key and label".
    assert user_dict_xml.normalize_column_type("text") == "текстовое значение"
    assert (
        user_dict_xml.normalize_column_type("текстовое значение")
        == "текстовое значение"
    )


def test_normalize_column_type_rejects_unknown():
    # Dlya sebya: proverka scenariya "test normalize column type rejects unknown".
    with pytest.raises(ValueError):
        user_dict_xml.normalize_column_type("unknown")


def test_build_create_xml_with_multiple_columns_uses_repeater_groups():
    # Dlya sebya: proverka scenariya "test build create xml with multiple columns uses repeater groups".
    xml_body = user_dict_xml.build_create_user_dict_xml(
        "test_dict",
        columns=[
            {"name": "name", "type": "text", "required": True},
            {"name": "is_active", "type": "bool", "required": False},
        ],
    )
    root = ET.fromstring(xml_body)
    rep = root.find(".//repeater[@alias='table_values']")
    assert rep is not None
    groups = [child for child in rep if child.tag == "group"]
    assert len(groups) == 2


def test_build_create_xml_with_preset():
    # Dlya sebya: proverka scenariya "test build create xml with preset".
    xml_body = user_dict_xml.build_create_user_dict_xml(
        "test_dict",
        preset="base_card",
    )
    root = ET.fromstring(xml_body)
    rep = root.find(".//repeater[@alias='table_values']")
    assert rep is not None
    groups = [child for child in rep if child.tag == "group"]
    assert len(groups) == 3


def test_build_search_xml_has_column_and_value_inside_filter_group():
    # Dlya sebya: proverka scenariya "test build search xml has column and value inside filter group".
    xml_body = user_dict_xml.build_query_single_user_dict_xml(
        "test_dict",
        filters=[{"column": "name", "value": "Ivan"}],
    )
    root = ET.fromstring(xml_body)
    rep = root.find(".//repeater[@alias='table_filters']")
    assert rep is not None
    groups = [child for child in rep if child.tag == "group"]
    assert len(groups) == 1
    aliases = [node.get("alias") for node in groups[0]]
    assert "column" in aliases
    assert "column_value" in aliases


def test_build_remove_rows_by_filters_does_not_send_empty_row_ids():
    # Dlya sebya: proverka scenariya "test build remove rows by filters does not send empty row ids".
    xml_body = user_dict_xml.build_remove_from_user_dict_xml(
        "test_dict",
        filters=[{"column": "description", "condition": "Равно", "value": "x"}],
    )
    root = ET.fromstring(xml_body)
    row_ids_rep = root.find(".//repeater[@alias='removed_row_ids']")
    assert row_ids_rep is not None
    assert len(list(row_ids_rep)) == 0

    filters_rep = root.find(".//repeater[@alias='table_filters']")
    assert filters_rep is not None
    groups = [child for child in filters_rep if child.tag == "group"]
    assert len(groups) == 1
    aliases = [node.get("alias") for node in list(groups[0])]
    assert aliases == ["column", "condition", "column_value"]


def test_build_remove_rows_by_ids_uses_group_items():
    # Dlya sebya: proverka scenariya "test build remove rows by ids uses group items".
    xml_body = user_dict_xml.build_remove_from_user_dict_xml(
        "test_dict",
        row_ids=["{id-1}", "{id-2}"],
    )
    root = ET.fromstring(xml_body)
    row_ids_rep = root.find(".//repeater[@alias='removed_row_ids']")
    assert row_ids_rep is not None
    groups = [child for child in row_ids_rep if child.tag == "group"]
    assert len(groups) == 2
    values = [n.text for n in row_ids_rep.findall(".//group/*[@alias='removed_row_id']")]
    assert values == ["{id-1}", "{id-2}"]


def test_build_select_fields_xml_sets_default_limit_offset_and_clears_empty_repeaters():
    # Dlya sebya: proverka scenariya "test build select fields xml sets default limit offset and clears empty repeaters".
    xml_body = user_dict_xml.build_select_fields_user_dict_xml("test_dict")
    root = ET.fromstring(xml_body)

    limit = root.find(".//*[@alias='table_limit']")
    offset = root.find(".//*[@alias='table_offset']")
    assert limit is not None and limit.text == "100000"
    assert offset is not None and offset.text == "0"

    filters_rep = root.find(".//repeater[@alias='table_filters']")
    order_rep = root.find(".//repeater[@alias='table_order_by_conditions']")
    assert filters_rep is not None and len(list(filters_rep)) == 0
    assert order_rep is not None and len(list(order_rep)) == 0


def test_build_update_xml_uses_single_grouped_row_with_explicit_uuid():
    # Dlya sebya: proverka scenariya "test build update xml uses single grouped row with explicit uuid".
    xml_body = user_dict_xml.build_update_user_dict_xml(
        "test_dict",
        "{row-1}",
        {"description": "updated"},
    )
    root = ET.fromstring(xml_body)

    rows_rep = root.find(".//repeater[@alias='user_table_rows']")
    assert rows_rep is not None
    groups = [child for child in rows_rep if child.tag == "group"]
    assert len(groups) == 1

    row_id = rows_rep.find(".//group/*[@alias='table_row_uuid']")
    assert row_id is not None
    assert row_id.text == "{row-1}"

    filters_rep = rows_rep.find(".//group/*[@alias='table_filters']")
    assert filters_rep is not None
    assert len(list(filters_rep)) == 0

    val = rows_rep.find(".//group/*[@alias='table_values']/*[@name='description']")
    assert val is not None
    assert val.text == "updated"


def test_build_query_user_dict_xml_uses_group_and_clears_joined_tables():
    # Dlya sebya: proverka scenariya "test build query user dict xml uses group and clears joined tables".
    xml_body = user_dict_xml.build_query_user_dict_xml("test_dict")
    root = ET.fromstring(xml_body)

    rep = root.find(".//repeater[@alias='user_table_names']")
    assert rep is not None
    groups = [child for child in rep if child.tag == "group"]
    assert len(groups) == 1

    name_node = rep.find(".//group/*[@alias='user_table_name']")
    assert name_node is not None
    assert name_node.text == "test_dict"

    joined_rep = rep.find(".//group/repeater[@alias='joined_tables']")
    assert joined_rep is not None
    assert len(list(joined_rep)) == 0


def test_build_query_user_dict_frame_xml_uses_group_for_name():
    # Dlya sebya: proverka scenariya "test build query user dict frame xml uses group for name".
    xml_body = user_dict_xml.build_query_user_dict_frame_xml("test_dict")
    root = ET.fromstring(xml_body)
    rep = root.find(".//repeater[@alias='user_table_names']")
    assert rep is not None
    groups = [child for child in rep if child.tag == "group"]
    assert len(groups) == 1
    node = rep.find(".//group/*[@alias='user_table_name']")
    assert node is not None
    assert node.text == "test_dict"
