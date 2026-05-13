import copy
import base64
import binascii
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from src.paragraph.xml_templates import load_xml_template


USER_DICT_COLUMN_TYPES: List[Dict[str, str]] = [
    {"key": "uuid", "label": "\u0443\u043d\u0438\u043a\u0430\u043b\u044c\u043d\u044b\u0439 \u0438\u0434\u0435\u043d\u0442\u0438\u0444\u0438\u043a\u0430\u0442\u043e\u0440"},
    {"key": "text", "label": "\u0442\u0435\u043a\u0441\u0442\u043e\u0432\u043e\u0435 \u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435"},
    {"key": "text_area", "label": "\u0442\u0435\u043a\u0441\u0442\u043e\u0432\u0430\u044f \u043e\u0431\u043b\u0430\u0441\u0442\u044c"},
    {"key": "int", "label": "\u0446\u0435\u043b\u043e\u0447\u0438\u0441\u043b\u0435\u043d\u043d\u043e\u0435 \u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435"},
    {"key": "double", "label": "\u0434\u0440\u043e\u0431\u043d\u043e\u0435 \u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435"},
    {"key": "datetime", "label": "\u0434\u0430\u0442\u0430/\u0432\u0440\u0435\u043c\u044f"},
    {"key": "date", "label": "\u0434\u0430\u0442\u0430"},
    {"key": "bool", "label": "\u0444\u043b\u0430\u0433"},
    {"key": "link", "label": "\u0441\u0441\u044b\u043b\u043a\u0430"},
    {"key": "shape", "label": "\u0444\u0438\u0433\u0443\u0440\u0430 \u043d\u0430 \u043a\u0430\u0440\u0442\u0435"},
    {"key": "marker", "label": "\u043c\u0430\u0440\u043a\u0435\u0440 \u043d\u0430 \u043a\u0430\u0440\u0442\u0435"},
    {"key": "file", "label": "\u0444\u0430\u0439\u043b"},
    {"key": "back_link", "label": "\u043e\u0431\u0440\u0430\u0442\u043d\u0430\u044f \u0441\u0441\u044b\u043b\u043a\u0430"},
    {"key": "tle", "label": "\u043f\u0430\u0440\u0430\u043c\u0435\u0442\u0440\u044b \u0418\u0421\u0417 (TLE)"},
    {"key": "json", "label": "json"},
    {"key": "external_link", "label": "\u0432\u043d\u0435\u0448\u043d\u044f\u044f \u0441\u0441\u044b\u043b\u043a\u0430"},
]

USER_DICT_CREATE_PRESETS: List[Dict[str, Any]] = [
    {
        "key": "single_text",
        "title": "\u041e\u0434\u0438\u043d \u0442\u0435\u043a\u0441\u0442\u043e\u0432\u044b\u0439 \u0441\u0442\u043e\u043b\u0431\u0435\u0446",
        "columns": [
            {"name": "name", "type": "text", "required": True},
        ],
    },
    {
        "key": "base_card",
        "title": "\u0411\u0430\u0437\u043e\u0432\u0430\u044f \u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0430",
        "columns": [
            {"name": "name", "type": "text", "required": True},
            {"name": "description", "type": "text_area", "required": False},
            {"name": "is_active", "type": "bool", "required": True},
        ],
    },
    {
        "key": "with_dates",
        "title": "\u0421 \u0434\u0430\u0442\u0430\u043c\u0438",
        "columns": [
            {"name": "name", "type": "text", "required": True},
            {"name": "created_at", "type": "datetime", "required": False},
            {"name": "event_date", "type": "date", "required": False},
        ],
    },
]

_COLUMN_TYPE_BY_KEY = {item["key"]: item["label"] for item in USER_DICT_COLUMN_TYPES}
_COLUMN_TYPE_BY_LABEL_LOWER = {
    item["label"].lower(): item["label"] for item in USER_DICT_COLUMN_TYPES
}
_CREATE_PRESET_BY_KEY = {item["key"]: item for item in USER_DICT_CREATE_PRESETS}


def get_column_type_help() -> List[Dict[str, str]]:
    # Dlya sebya: servisnaya operaciya "get column type help".
    return copy.deepcopy(USER_DICT_COLUMN_TYPES)


def get_create_presets_help() -> List[Dict[str, Any]]:
    # Dlya sebya: servisnaya operaciya "get create presets help".
    return copy.deepcopy(USER_DICT_CREATE_PRESETS)


def normalize_column_type(raw: str) -> str:
    # Dlya sebya: servisnaya operaciya "normalize column type".
    value = (raw or "").strip()
    if not value:
        raise ValueError("column.type must not be empty")

    by_key = _COLUMN_TYPE_BY_KEY.get(value.lower())
    if by_key:
        return by_key

    by_label = _COLUMN_TYPE_BY_LABEL_LOWER.get(value.lower())
    if by_label:
        return by_label

    allowed = ", ".join(item["key"] for item in USER_DICT_COLUMN_TYPES)
    raise ValueError(f"unsupported column.type '{raw}'. Use one of keys: {allowed}")


def _find_first_by_alias(root: ET.Element, alias: str) -> ET.Element:
    # Dlya sebya: servisnyy helper (find first by alias).
    node = root.find(f".//*[@alias='{alias}']")
    if node is None:
        raise ValueError(f"alias not found: {alias}")
    return node


def _find_repeater(root: ET.Element, alias: str) -> ET.Element:
    # Dlya sebya: servisnyy helper (find repeater).
    node = root.find(f".//repeater[@alias='{alias}']")
    if node is None:
        raise ValueError(f"repeater alias not found: {alias}")
    return node


def _clear_children(node: ET.Element) -> None:
    # Dlya sebya: servisnyy helper (clear children).
    for child in list(node):
        node.remove(child)


def _set_text_by_alias(root: ET.Element, alias: str, value: str) -> None:
    # Dlya sebya: servisnyy helper (set text by alias).
    node = _find_first_by_alias(root, alias)
    node.text = value


def _set_checkbox_by_alias(root: ET.Element, alias: str, value: bool) -> None:
    # Dlya sebya: servisnyy helper (set checkbox by alias).
    node = _find_first_by_alias(root, alias)
    node.text = "true" if value else "false"


def _set_checkbox_by_alias_if_exists(root: ET.Element, alias: str, value: bool) -> None:
    # Dlya sebya: v nekotoryh versiyah XML alias mozhet otsutstvovat' (nuzhen myagkiy fallback).
    node = root.find(f".//*[@alias='{alias}']")
    if node is not None:
        node.text = "true" if value else "false"


def _set_spin_by_alias(root: ET.Element, alias: str, value: int) -> None:
    # Dlya sebya: servisnyy helper (set spin by alias).
    node = _find_first_by_alias(root, alias)
    node.text = str(value)


def _append_repeater_item(
    repeater: ET.Element,
    template_nodes: List[ET.Element],
    values_by_alias: Dict[str, Any],
) -> None:
    # Dlya sebya: servisnyy helper (append repeater item).
    if not template_nodes:
        return

    # In Paragraph repeaters each row should be wrapped into <group>,
    # including rows that contain a single field.
    group = ET.SubElement(repeater, "group")
    for src in template_nodes:
        node = copy.deepcopy(src)
        alias = node.get("alias")
        if alias and alias in values_by_alias:
            value = values_by_alias[alias]
            node.text = "" if value is None else str(value)
        group.append(node)


def _add_value_param(parent: ET.Element, name: str, value: Any) -> None:
    # Dlya sebya: servisnyy helper (add value param).
    if isinstance(value, dict):
        file_param_type = str(value.get("_file_param_type") or "").strip().lower()
        raw_b64 = (
            value.get("content_base64")
            or value.get("data_base64")
            or value.get("base64")
        )
        if raw_b64 is not None:
            payload = str(raw_b64).strip()
            if payload.startswith("base64,"):
                payload = payload[7:].strip()
            if payload.startswith("data:") and ";base64," in payload:
                payload = payload.split(";base64,", 1)[1].strip()
            # validate base64 once to fail early on broken upload payload
            try:
                raw = base64.b64decode(payload, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError(
                    f"column '{name}' contains invalid base64 file payload"
                ) from exc
            normalized_b64 = base64.b64encode(raw).decode("ascii")
            # Some builds expect binary_param, others input_file for file columns.
            # Keep backward compatibility: default is binary_param, optional override by _file_param_type.
            xml_tag = "input_file" if file_param_type == "input_file" else "binary_param"
            el = ET.SubElement(parent, xml_tag)
            el.set("name", name)
            filename = str(value.get("filename") or value.get("file_name") or "").strip()
            if filename:
                el.set("filename", filename)
            el.text = normalized_b64
            return

    if isinstance(value, bool):
        el = ET.SubElement(parent, "check_box")
        el.set("name", name)
        el.text = "true" if value else "false"
        return
    if isinstance(value, int):
        el = ET.SubElement(parent, "spin_box")
        el.set("name", name)
        el.set("type", "int")
        el.text = str(value)
        return
    if isinstance(value, float):
        el = ET.SubElement(parent, "spin_box")
        el.set("name", name)
        el.set("type", "double")
        el.text = str(value)
        return
    el = ET.SubElement(parent, "text_field")
    el.set("name", name)
    el.text = "" if value is None else str(value)


def _xml_to_str(root: ET.Element) -> str:
    # Dlya sebya: servisnyy helper (xml to str).
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def _default_create_columns() -> List[Dict[str, Any]]:
    # Dlya sebya: servisnyy helper (default create columns).
    return [{"name": "name", "type": "text", "required": True}]


def _normalize_create_columns(columns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Dlya sebya: servisnyy helper (normalize create columns).
    normalized: List[Dict[str, Any]] = []
    for idx, column in enumerate(columns):
        name = str(column.get("name", "")).strip()
        if not name:
            raise ValueError(f"columns[{idx}].name must not be empty")

        normalized.append(
            {
                "name": name,
                "type": normalize_column_type(str(column.get("type", "text"))),
                "required": bool(column.get("required", True)),
                "ref_dict": str(column.get("ref_dict", "")).strip(),
                "ref_column": str(column.get("ref_column", "")).strip(),
                "cascade": bool(column.get("cascade", False)),
            }
        )
    return normalized


def _resolve_create_columns(
    columns: Optional[List[Dict[str, Any]]],
    preset: Optional[str],
) -> List[Dict[str, Any]]:
    # Dlya sebya: servisnyy helper (resolve create columns).
    if columns:
        return _normalize_create_columns(columns)

    if preset:
        preset_key = preset.strip()
        preset_data = _CREATE_PRESET_BY_KEY.get(preset_key)
        if not preset_data:
            available = ", ".join(sorted(_CREATE_PRESET_BY_KEY.keys()))
            raise ValueError(
                f"unsupported preset '{preset}'. Use one of: {available}"
            )
        return _normalize_create_columns(preset_data["columns"])

    return _normalize_create_columns(_default_create_columns())


def build_create_user_dict_xml(
    dict_name: str,
    columns: Optional[List[Dict[str, Any]]] = None,
    preset: Optional[str] = None,
) -> str:
    # Dlya sebya: sobirayu XML dlya operacii "build create user dict xml".
    root = ET.fromstring(load_xml_template("create_user_dict_v1"))
    _set_text_by_alias(root, "user_table_name", dict_name)
    effective_columns = _resolve_create_columns(columns, preset)

    repeater = _find_repeater(root, "table_values")
    template_children = list(repeater)
    if not template_children:
        raise ValueError("table_values template is empty")
    _clear_children(repeater)

    for col in effective_columns:
        group = ET.SubElement(repeater, "group")
        for template_node in template_children:
            node = copy.deepcopy(template_node)
            alias = node.get("alias", "")
            if alias == "user_table_column":
                node.text = col["name"]
            elif alias == "user_table_type":
                node.text = col["type"]
            elif alias == "check":
                node.text = "true" if col["required"] else "false"
            elif alias == "user_table_ref":
                node.text = col["ref_dict"]
            elif alias == "user_table_column_ref":
                node.text = col["ref_column"]
            elif alias == "check_cascade":
                node.text = "true" if col["cascade"] else "false"
            group.append(node)

    return _xml_to_str(root)


def build_remove_user_dict_xml(dict_name: str) -> str:
    # Dlya sebya: sobirayu XML dlya operacii "build remove user dict xml".
    root = ET.fromstring(load_xml_template("remove_user_dict"))
    _set_text_by_alias(root, "user_table_name", dict_name)
    return _xml_to_str(root)


def build_query_user_dict_frame_xml(dict_name: Optional[str]) -> str:
    # Dlya sebya: sobirayu XML dlya operacii "build query user dict frame xml".
    root = ET.fromstring(load_xml_template("query_user_dict_frame"))
    rep = _find_repeater(root, "user_table_names")
    template = list(rep)
    _clear_children(rep)
    if dict_name and template:
        _append_repeater_item(
            rep,
            template,
            {"user_table_name": dict_name},
        )
    return _xml_to_str(root)


def build_query_user_dict_xml(dict_name: Optional[str], *, prefer_v2: bool = True) -> str:
    # Dlya sebya: sobirayu XML dlya operacii "build query user dict xml".
    if prefer_v2:
        try:
            root = ET.fromstring(load_xml_template("query_user_dict_v2"))
            # query_user_dict_v2 uses explicit version block.
            try:
                _set_spin_by_alias(root, "major", 2)
                _set_spin_by_alias(root, "minor", 0)
            except ValueError:
                pass
        except FileNotFoundError:
            root = ET.fromstring(load_xml_template("query_user_dict"))
    else:
        root = ET.fromstring(load_xml_template("query_user_dict"))
    rep = _find_repeater(root, "user_table_names")
    template = list(rep)
    _clear_children(rep)
    if dict_name and template:
        group = ET.SubElement(rep, "group")
        for src in template:
            node = copy.deepcopy(src)
            alias = node.get("alias", "")
            if alias == "user_table_name":
                node.text = dict_name
            elif node.tag == "repeater" and alias == "joined_tables":
                # joined tables are optional; do not send empty placeholders.
                _clear_children(node)
            group.append(node)
    return _xml_to_str(root)


def build_query_user_dict_metainfo_xml(dict_name: str) -> str:
    # Dlya sebya: sobirayu XML dlya operacii "build query user dict metainfo xml".
    root = ET.fromstring(load_xml_template("query_user_dict_metainfo"))
    _set_text_by_alias(root, "user_dict_name", dict_name)
    return _xml_to_str(root)


def build_select_fields_user_dict_xml(
    dict_name: str,
    *,
    filters: Optional[List[Dict[str, str]]] = None,
    order_by: Optional[List[Dict[str, str]]] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    expand_links: bool = False,
    template_alias: str = "select_fields_user_dict_v1",
) -> str:
    # Dlya sebya: sobirayu XML dlya operacii "build select fields user dict xml".
    root = ET.fromstring(load_xml_template(template_alias))
    _set_text_by_alias(root, "user_table_name", dict_name)
    _set_checkbox_by_alias_if_exists(root, "user_table_links_is_expand", expand_links)
    # In Paragraph, empty table_limit can be interpreted as 0 and return no rows.
    # Use explicit defaults when caller does not provide pagination.
    _set_spin_by_alias(root, "table_limit", limit if limit is not None else 100000)
    _set_spin_by_alias(root, "table_offset", offset if offset is not None else 0)

    rep = _find_repeater(root, "table_filters")
    template = list(rep)
    _clear_children(rep)
    if filters and template:
        for f in filters:
            _append_repeater_item(
                rep,
                template,
                {
                    "column": f.get("column", ""),
                    "condition": f.get("condition", "\u0420\u0430\u0432\u043d\u043e"),
                    "column_value": f.get("value", ""),
                },
            )

    rep = _find_repeater(root, "table_order_by_conditions")
    template = list(rep)
    _clear_children(rep)
    if order_by and template:
        for o in order_by:
            _append_repeater_item(
                rep,
                template,
                {
                    "order_column": o.get("column", ""),
                    "order_condition": o.get(
                        "direction",
                        "\u0412\u043e\u0437\u0440\u0430\u0441\u0442\u0430\u043d\u0438\u044e",
                    ),
                },
            )

    return _xml_to_str(root)


def build_insert_user_dict_xml(
    dict_name: str,
    rows: List[Dict[str, Any]],
) -> str:
    # Dlya sebya: sobirayu XML dlya operacii "build insert user dict xml".
    root = ET.fromstring(load_xml_template("insert_user_dict"))
    _set_text_by_alias(root, "user_table_name", dict_name)
    rep = _find_repeater(root, "table_values")
    _clear_children(rep)

    for row in rows:
        group = ET.SubElement(rep, "group")
        for k, v in row.items():
            _add_value_param(group, k, v)
    return _xml_to_str(root)


def build_query_single_user_dict_xml(
    dict_name: str,
    filters: List[Dict[str, str]],
) -> str:
    # Dlya sebya: sobirayu XML dlya operacii "build query single user dict xml".
    root = ET.fromstring(load_xml_template("query_single_user_dict"))
    _set_text_by_alias(root, "user_table_name", dict_name)
    rep = _find_repeater(root, "table_filters")
    template = list(rep)
    _clear_children(rep)
    if template:
        for f in filters:
            _append_repeater_item(
                rep,
                template,
                {
                    "column": f.get("column", ""),
                    "column_value": f.get("value", ""),
                },
            )
    return _xml_to_str(root)


def build_update_user_dict_xml(
    dict_name: str,
    row_id: str,
    values: Dict[str, Any],
) -> str:
    # Dlya sebya: sobirayu XML dlya operacii "build update user dict xml".
    root = ET.fromstring(load_xml_template("update_user_dict"))
    _set_text_by_alias(root, "user_table_name", dict_name)

    # Repeaters in Paragraph request payload are expected as rows (<group>...).
    # Build exactly one target row to avoid broad update operations.
    rows_rep = _find_repeater(root, "user_table_rows")
    template_nodes = list(rows_rep)
    _clear_children(rows_rep)

    row_group = ET.SubElement(rows_rep, "group")
    for src in template_nodes:
        node = copy.deepcopy(src)
        alias = node.get("alias", "")
        if alias == "table_row_uuid":
            node.text = row_id
        elif alias == "table_filters":
            # Update by explicit row id only.
            _clear_children(node)
        elif alias == "table_values":
            _clear_children(node)
            for k, v in values.items():
                _add_value_param(node, k, v)
        row_group.append(node)

    return _xml_to_str(root)


def build_remove_from_user_dict_xml(
    dict_name: str,
    *,
    row_ids: Optional[List[str]] = None,
    filters: Optional[List[Dict[str, str]]] = None,
) -> str:
    # Dlya sebya: sobirayu XML dlya operacii "build remove from user dict xml".
    root = ET.fromstring(load_xml_template("remove_from_user_dict"))
    _set_text_by_alias(root, "user_table_name", dict_name)

    rep = _find_repeater(root, "removed_row_ids")
    template = list(rep)
    _clear_children(rep)
    if row_ids and template:
        for rid in row_ids:
            _append_repeater_item(
                rep,
                template,
                {"removed_row_id": rid},
            )

    rep = _find_repeater(root, "table_filters")
    template = list(rep)
    _clear_children(rep)
    if filters and template:
        for f in filters:
            _append_repeater_item(
                rep,
                template,
                {
                    "column": f.get("column", ""),
                    "condition": f.get("condition", "\u0420\u0430\u0432\u043d\u043e"),
                    "column_value": f.get("value", ""),
                },
            )

    return _xml_to_str(root)


def build_documentfilesget_xml(file_ids: List[str]) -> str:
    # Dlya sebya: sobirayu XML dlya operacii "build documentfilesget xml".
    if not file_ids:
        raise ValueError("file_ids must not be empty")

    root = ET.fromstring(load_xml_template("documentfilesget"))
    rep = _find_repeater(root, "files_id")
    template = list(rep)
    _clear_children(rep)

    if not template:
        raise ValueError("files_id template is empty")

    for file_id in file_ids:
        raw = str(file_id or "").strip()
        if not raw:
            continue
        wrapped = raw
        _append_repeater_item(
            rep,
            template,
            {"file_id": wrapped},
        )

    return _xml_to_str(root)
