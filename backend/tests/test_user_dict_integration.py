import os
import time
import xml.etree.ElementTree as ET
import logging

import pytest

from src.ishd.client import IshdClient
from src.ishd.proto import Ai_Report_pb2
from src.paragraph.xml_templates import load_xml_template

logger = logging.getLogger(__name__)


def _set_first_text_by_alias(root: ET.Element, alias: str, value: str) -> None:
    # Dlya sebya: vspomogatelnyy shag (set first text by alias).
    node = root.find(f".//*[@alias='{alias}']")
    if node is None:
        raise RuntimeError(f"alias not found: {alias}")
    node.text = value


def _set_first_combobox_by_alias(root: ET.Element, alias: str, value: str) -> None:
    # Dlya sebya: vspomogatelnyy shag (set first combobox by alias).
    node = root.find(f".//combo_box[@alias='{alias}']")
    if node is None:
        raise RuntimeError(f"combo_box alias not found: {alias}")
    node.text = value


def _set_first_checkbox_by_alias(root: ET.Element, alias: str, value: str) -> None:
    # Dlya sebya: vspomogatelnyy shag (set first checkbox by alias).
    node = root.find(f".//check_box[@alias='{alias}']")
    if node is None:
        raise RuntimeError(f"check_box alias not found: {alias}")
    node.text = value


def _xml_to_str(root: ET.Element) -> str:
    # Dlya sebya: vspomogatelnyy shag (xml to str).
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def _make_test_dict_name() -> str:
    # Dlya sebya: vspomogatelnyy shag (make test dict name).
    base = os.getenv("PARAGRAF_TEST_DICT", "").strip()
    if base:
        return base
    return f"par_test_{int(time.time())}"


def _load_xml(name: str) -> ET.Element:
    # Dlya sebya: vspomogatelnyy shag (load xml).
    xml_text = load_xml_template(name)
    return ET.fromstring(xml_text)


def _ensure_done(resp) -> None:
    # Dlya sebya: vspomogatelnyy shag (ensure done).
    assert resp.report.code == Ai_Report_pb2.ReportCode.DONE, (
        f"ISHD report not DONE: {resp.report.code} {resp.report.description}"
    )


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_ISHD_TESTS") != "1", reason="set RUN_ISHD_TESTS=1")
async def test_user_dict_flow_basic():
    # Dlya sebya: proverka scenariya "test user dict flow basic".
    dict_name = _make_test_dict_name()
    keep_dict = os.getenv("KEEP_CREATED_DICT") == "1"
    create_only = os.getenv("CREATE_ONLY") == "1"
    logger.info("TEST dict_name=%s keep=%s create_only=%s", dict_name, keep_dict, create_only)

    client = IshdClient()
    await client.connect()
    try:
        # create_user_dict_v1
        root = _load_xml("create_user_dict_v1")
        _set_first_text_by_alias(root, "user_table_name", dict_name)
        _set_first_text_by_alias(root, "user_table_column", "name")
        _set_first_combobox_by_alias(root, "user_table_type", "текстовое значение")
        _set_first_checkbox_by_alias(root, "check", "true")

        alias = root.get("alias") or "create_user_dict_v1"

        resp = await client.send_paragraph_xml(
            alias=alias,
            xml_body=_xml_to_str(root),
            accept_action=True,
        )
        _ensure_done(resp)

        if create_only:
            return

        # query_user_dict_frame
        root = _load_xml("query_user_dict_frame")
        _set_first_text_by_alias(root, "user_table_name", dict_name)
        alias = root.get("alias") or "query_user_dict_frame"

        resp = await client.send_paragraph_xml(
            alias=alias,
            xml_body=_xml_to_str(root),
        )
        _ensure_done(resp)

        # query_user_dict_metainfo
        root = _load_xml("query_user_dict_metainfo")
        _set_first_text_by_alias(root, "user_dict_name", dict_name)
        alias = root.get("alias") or "query_user_dict_metainfo"

        resp = await client.send_paragraph_xml(
            alias=alias,
            xml_body=_xml_to_str(root),
        )
        _ensure_done(resp)

        # select_fields_user_dict_v1
        root = _load_xml("select_fields_user_dict_v1")
        _set_first_text_by_alias(root, "user_table_name", dict_name)
        alias = root.get("alias") or "select_fields_user_dict_v1"

        resp = await client.send_paragraph_xml(
            alias=alias,
            xml_body=_xml_to_str(root),
        )
        _ensure_done(resp)

        if not keep_dict:
            # remove_user_dict
            root = _load_xml("remove_user_dict")
            _set_first_text_by_alias(root, "user_table_name", dict_name)
            alias = root.get("alias") or "remove_user_dict"

            resp = await client.send_paragraph_xml(
                alias=alias,
                xml_body=_xml_to_str(root),
            )
            _ensure_done(resp)
    finally:
        await client.close()
