import logging

from src.ishd.client import IshdClient

logger = logging.getLogger(__name__)

_ishd_client: IshdClient | None = None


async def init_ishd() -> None:
    # Dlya sebya: public shag po rabote s ISHD (init ishd).
    global _ishd_client

    if _ishd_client is not None:
        # уже инициализирован
        return

    client = IshdClient()
    logger.info("Initializing ISHD client...")
    await client.connect()

    _ishd_client = client


async def shutdown_ishd() -> None:
    # Dlya sebya: public shag po rabote s ISHD (shutdown ishd).
    global _ishd_client

    if _ishd_client is None:
        return

    logger.info("Shutting down ISHD client...")
    try:
        await _ishd_client.close()
    except Exception:
        logger.exception("Error during ISHD close")

    _ishd_client = None


def get_ishd_client() -> IshdClient:
    # Dlya sebya: public shag po rabote s ISHD (get ishd client).
    if _ishd_client is None:
        raise RuntimeError("ISHD client is not initialized. Call init_ishd() on startup.")
    return _ishd_client
