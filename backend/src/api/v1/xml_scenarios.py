from fastapi import APIRouter, Depends, HTTPException
from src.services.xml_templates import list_xml_templates, load_xml_template
from src.ishd.client import IshdClient
from src.api.v1._ishd_runtime import get_ishd_client_for_request

router = APIRouter(prefix="/xml-templates", tags=["xml-templates"])

@router.get("/")
def get_templates_list():
    # Dlya sebya: endpoint "get_templates_list" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    templates = [t.dict() for t in list_xml_templates()]
    return templates

@router.get("/{alias}")
def get_template(alias: str):
    # Dlya sebya: endpoint "get_template" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    try:
        content = load_xml_template(alias)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")

    return {"alias": alias, "content": content}

@router.post(
    "/run",
    summary="Запустить базовый набор XML",
    description="Прогоняет несколько XML-шаблонов через ИШД. Поддерживает target_id.",
)
async def run_xml_tests(client: IshdClient = Depends(get_ishd_client_for_request)):
    # Dlya sebya: endpoint "run_xml_tests" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    xml_queries = [
        "create_user_dict_v1.xml", 
        "query_user_dict.xml",
    ]

    result = {}
    for query in xml_queries:
        xml_query = load_xml_template(query)
        try:
            response = await client.send_paragraph_xml(alias=query.replace(".xml", ""), xml_body=xml_query)
            result[query] = {"status": "ok", "response": response}
        except Exception as e:
            result[query] = {"status": "fail", "error": str(e)}
    
    return result


@router.post(
    "/run/{alias}",
    summary="Запустить один XML-шаблон",
    description="Выполняет выбранный шаблон через ИШД. Поддерживает target_id.",
)
async def run_xml_test(alias: str, client: IshdClient = Depends(get_ishd_client_for_request)):
    # Dlya sebya: endpoint "run_xml_test" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    try:
        xml_query = load_xml_template(alias)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        response = await client.send_paragraph_xml(alias=alias, xml_body=xml_query)
        return {"status": "ok", "response": response}
    except Exception as e:
        return {"status": "fail", "error": str(e)}
