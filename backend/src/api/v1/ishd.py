from fastapi import APIRouter, Depends, HTTPException, status
from src.ishd.client import IshdClient
from src.ishd.client import IshdError
from src.api.v1._ishd_runtime import get_ishd_client_for_request

router = APIRouter(prefix="/ishd", tags=["ishd"])


@router.get(
    "/modules",
    summary="Список модулей ИШД",
    description="Возвращает список машин/модулей. Поддерживает target_id и X-Target-ID.",
)
async def get_modules(client: IshdClient = Depends(get_ishd_client_for_request)):
    # Dlya sebya: endpoint "get_modules" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    try:
        # Получаем ответ от клиента ИШД
        resp = await client.request_module_list()
        # Используем правильный атрибут для получения списка модулей
        module_list = resp.module_list_response  # Применяем module_list_response
    except IshdError as e:
        # В случае ошибки от ИШД, выбрасываем исключение
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ISHD error: {e}",
        )

    # Формируем ответ в нужном формате
    return {
        "machines": [
            {
                "id": m.machine_id,
                "name": m.machine_name,
                "online": m.online,
                "localhost": getattr(m, "localhost", False),
                "ip_address": getattr(m, "ip_address", ""),
                "machine_alias": getattr(m, "machine_alias", ""),
                "modules": [
                    {
                        "id": mod.id,
                        "name": mod.name,
                        "alias": mod.alias_id,
                        "version": mod.version,
                        "online": mod.online,
                        "authorized": mod.authorized,
                    }
                    for mod in m.modules  # Перебираем модули каждой машины
                ],
            }
            for m in module_list.list  # Перебираем список машин
        ]
    }
