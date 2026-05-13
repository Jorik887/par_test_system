from fastapi import APIRouter, Query

from src.services import perf_monitor


router = APIRouter(prefix="/debug/perf", tags=["debug-perf"])


@router.get(
    "/summary",
    summary="Perf Summary (top slow operations)",
    description="In-memory timing summary for recent backend endpoints/operations.",
)
async def perf_summary(
    limit: int = Query(default=5, ge=1, le=50),
    recent_limit: int = Query(default=100, ge=1, le=500),
):
    return {
        "top_endpoints": perf_monitor.top_slowest(kind="endpoint", limit=limit),
        "top_operations": perf_monitor.top_slowest(kind="operation", limit=limit),
        "recent_endpoints": perf_monitor.recent(kind="endpoint", limit=recent_limit),
        "recent_operations": perf_monitor.recent(kind="operation", limit=recent_limit),
    }

