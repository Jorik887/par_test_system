from fastapi import APIRouter

router = APIRouter(
    prefix="/health",
    tags=["health"],
)


@router.get("", summary="Проверка состояния сервиса")
async def health_check():
    # Dlya sebya: endpoint "health_check" ? obrabatyvayu zapros i vozvrashchayu rezultat.
    return {"status": "ok"}
