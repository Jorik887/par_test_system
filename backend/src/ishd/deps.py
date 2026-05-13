import logging
from src.ishd.client import IshdClient

logger = logging.getLogger(__name__)

_ishd_client: IshdClient | None = None


async def init_ishd() -> None:
    # Dlya sebya: public shag po rabote s ISHD (init ishd).
    global _ishd_client
    if _ishd_client is not None:
        return

    client = IshdClient()
    try:
        await client.connect()
    except Exception as e:
        logger.error("Error initializing ISHD client: %s", e)
        raise
    _ishd_client = client

def get_ishd_client() -> IshdClient:
    # Dlya sebya: public shag po rabote s ISHD (get ishd client).
    if _ishd_client is None:
        raise RuntimeError("ISHD client is not initialized. Call init_ishd() on startup.")
    return _ishd_client

async def shutdown_ishd() -> None:
    # Dlya sebya: public shag po rabote s ISHD (shutdown ishd).
    global _ishd_client
    if _ishd_client is None:
        return
    await _ishd_client.disconnect()
    _ishd_client = None
