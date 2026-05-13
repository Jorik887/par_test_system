from typing import Dict, Any

from src.ishd.client import IshdClient, IshdError
from src.ishd.proto import Ai_Documents_pb2, Ai_Report_pb2


def _response_to_dict(resp: Ai_Documents_pb2.DocumentResponse) -> Dict[str, Any]:
    # Dlya sebya: vnutrenniy shag ISHD-klienta (response to dict).
    code = resp.report.code
    # В сгенерированном коде enum обычно не имеет .name, поэтому страхуемся:
    try:
        code_name = Ai_Report_pb2.ReportCode.Name(code)
    except ValueError:
        code_name = str(int(code))

    return {
        "report_code": int(code),
        "report_code_name": code_name,
        "description": resp.report.description,
        # при желании сюда можно добавить поля документа, состояние и т.п.
    }


async def run_paragraph_xml(
    client: IshdClient,
    *,
    alias: str,
    xml_body: str,
    doc_type: str = "paragraph_xml",
) -> Dict[str, Any]:
    # Dlya sebya: public shag po rabote s ISHD (run paragraph xml).
    try:
        resp = await client.send_paragraph_xml(
            alias=alias,
            xml_body=xml_body,
            doc_type=doc_type,
        )
    except IshdError as e:
        # Можно перекинуть наверх, но для удобства дадим такой формат:
        return {
            "report_code": None,
            "report_code_name": "ISHD_ERROR",
            "description": str(e),
        }

    return _response_to_dict(resp)


# ==================================================================== #
# Конкретные сценарии для XML Параграфа
# ==================================================================== #
#
# Предположение: alias для EDM = имя XML-файла без .xml:
#   create_user_dict_v1.xml        -> "create_user_dict_v1"
#   remove_user_dict.xml           -> "remove_user_dict"
#   query_user_dict_frame.xml      -> "query_user_dict_frame"
#   query_user_dict.xml            -> "query_user_dict"
#   insert_user_dict.xml           -> "insert_user_dict"
#   query_single_user_dict.xml     -> "query_single_user_dict"
#   remove_from_user_dict.xml      -> "remove_from_user_dict"
#   select_fields_user_dict_v1.xml -> "select_fields_user_dict_v1"
#   update_user_dict.xml           -> "update_user_dict"
#   query_user_dict_metainfo.xml   -> "query_user_dict_metainfo"
#
# Если в документации Параграфа alias должен быть другим — просто
# меняем строку alias в нужной функции, интерфейс останется тем же.


async def run_create_user_dict_v1(
    client: IshdClient,
    xml_body: str,
) -> Dict[str, Any]:
    # Dlya sebya: public shag po rabote s ISHD (run create user dict v1).
    return await run_paragraph_xml(
        client,
        alias="create_user_dict_v1",
        xml_body=xml_body,
    )


async def run_remove_user_dict(
    client: IshdClient,
    xml_body: str,
) -> Dict[str, Any]:
    # Dlya sebya: public shag po rabote s ISHD (run remove user dict).
    return await run_paragraph_xml(
        client,
        alias="remove_user_dict",
        xml_body=xml_body,
    )


async def run_query_user_dict_frame(
    client: IshdClient,
    xml_body: str,
) -> Dict[str, Any]:
    # Dlya sebya: public shag po rabote s ISHD (run query user dict frame).
    return await run_paragraph_xml(
        client,
        alias="query_user_dict_frame",
        xml_body=xml_body,
    )


async def run_query_user_dict(
    client: IshdClient,
    xml_body: str,
) -> Dict[str, Any]:
    # Dlya sebya: public shag po rabote s ISHD (run query user dict).
    return await run_paragraph_xml(
        client,
        alias="query_user_dict",
        xml_body=xml_body,
    )


async def run_insert_user_dict(
    client: IshdClient,
    xml_body: str,
) -> Dict[str, Any]:
    # Dlya sebya: public shag po rabote s ISHD (run insert user dict).
    return await run_paragraph_xml(
        client,
        alias="insert_user_dict",
        xml_body=xml_body,
    )


async def run_query_single_user_dict(
    client: IshdClient,
    xml_body: str,
) -> Dict[str, Any]:
    # Dlya sebya: public shag po rabote s ISHD (run query single user dict).
    return await run_paragraph_xml(
        client,
        alias="query_single_user_dict",
        xml_body=xml_body,
    )


async def run_remove_from_user_dict(
    client: IshdClient,
    xml_body: str,
) -> Dict[str, Any]:
    # Dlya sebya: public shag po rabote s ISHD (run remove from user dict).
    return await run_paragraph_xml(
        client,
        alias="remove_from_user_dict",
        xml_body=xml_body,
    )


async def run_select_fields_user_dict_v1(
    client: IshdClient,
    xml_body: str,
) -> Dict[str, Any]:
    # Dlya sebya: public shag po rabote s ISHD (run select fields user dict v1).
    return await run_paragraph_xml(
        client,
        alias="select_fields_user_dict_v1",
        xml_body=xml_body,
    )


async def run_update_user_dict(
    client: IshdClient,
    xml_body: str,
) -> Dict[str, Any]:
    # Dlya sebya: public shag po rabote s ISHD (run update user dict).
    return await run_paragraph_xml(
        client,
        alias="update_user_dict",
        xml_body=xml_body,
    )


async def run_query_user_dict_metainfo(
    client: IshdClient,
    xml_body: str,
) -> Dict[str, Any]:
    # Dlya sebya: public shag po rabote s ISHD (run query user dict metainfo).
    return await run_paragraph_xml(
        client,
        alias="query_user_dict_metainfo",
        xml_body=xml_body,
    )
