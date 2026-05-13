from pathlib import Path
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
import logging
from src.config.settings import settings
from src.api.v1 import health, xml_scenarios, ishd as ishd_api, paragraph_docs, targets
from src.api.v1 import user_dicts
from src.api.v1 import user_dicts_rest
from src.api.v1 import perf as perf_api
from src.ishd.deps import init_ishd, shutdown_ishd
from src.services import perf_monitor

def create_app() -> FastAPI:
    # Dlya sebya: zdes sobirayetsya vse prilozhenie - middleware, routery i statika fronta.
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _perf_timing_middleware(request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000.0
        perf_monitor.record_endpoint(
            method=request.method,
            path=request.url.path,
            status_code=int(response.status_code),
            duration_ms=duration_ms,
        )
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
        return response

    @app.on_event("startup")
    async def _startup() -> None:
        # Uvicorn config often keeps app loggers at WARNING; enable ISHD flow logs for diagnostics.
        # Dlya sebya: vspomogatelnyy shag (startup).
        logging.getLogger("src.ishd.client").setLevel(logging.INFO)
        try:
            # Dlya sebya: default-ISHD ne dolzhen valit ves server, target-profile mogut rabotat otdelno.
            await init_ishd()
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Default ISHD client init failed on startup (server continues): %s",
                e,
            )

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        # Dlya sebya: vspomogatelnyy shag (shutdown).
        await shutdown_ishd()

    app.include_router(health.router)
    app.include_router(xml_scenarios.router)
    app.include_router(ishd_api.router)
    app.include_router(paragraph_docs.router)
    app.include_router(targets.router)
    app.include_router(user_dicts.router)
    app.include_router(user_dicts_rest.router)
    app.include_router(perf_api.router)

    # Dlya sebya: esli front est v repo, otdaem ego iz backenda po /ui.
    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    if (frontend_dir / "index.html").exists():
        app.mount("/ui", StaticFiles(directory=frontend_dir, html=True), name="ui")

        @app.get("/", include_in_schema=False)
        async def _root_redirect() -> RedirectResponse:
            # Dlya sebya: koren otkryvaet UI, a /docs ostayotsya dlya Swagger.
            return RedirectResponse(url="/ui")

    return app

app = create_app()
