import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query, Request
import httpx
from app.config import settings


_logger = logging.getLogger("control_center.proxy")
router = APIRouter(prefix="/api/proxy", tags=["Platform Proxy"])


async def _proxy_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    target_url = f"{settings.PLATFORM_URL.rstrip('/')}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(target_url, params=params)
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Platform API returned {resp.status_code}: {resp.text}"
                )
            return resp.json()
    except httpx.RequestError as exc:
        _logger.warning(f"Failed to reach Platform at {target_url}: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"Unable to connect to Platform service at {settings.PLATFORM_URL}: {exc}"
        ) from exc


async def _proxy_post(path: str, payload: Dict[str, Any]) -> Any:
    target_url = f"{settings.PLATFORM_URL.rstrip('/')}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(target_url, json=payload)
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Platform API returned {resp.status_code}: {resp.text}"
                )
            return resp.json()
    except httpx.RequestError as exc:
        _logger.warning(f"Failed to reach Platform at {target_url}: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"Unable to connect to Platform service at {settings.PLATFORM_URL}: {exc}"
        ) from exc


@router.get("/version")
async def get_platform_version():
    """Proxy Platform /version metadata including safety state."""
    return await _proxy_get("/version")


@router.get("/health")
async def get_platform_health():
    """Proxy Platform /health status."""
    return await _proxy_get("/health")


@router.get("/resources/current")
async def get_current_resources(
    namespace: str = Query(default="default", description="Target Kubernetes namespace"),
    workload: str = Query(default="demo-api", description="Target workload name"),
):
    """Proxy current observed resource state for the specified workload."""
    return await _proxy_get(
        "/api/v1/resources/current",
        params={"namespace": namespace, "workload": workload}
    )


@router.get("/history")
async def get_decision_history(
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    action: Optional[str] = Query(default=None),
    success: Optional[bool] = Query(default=None),
):
    """Proxy recent decision history."""
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if action:
        params["action"] = action
    if success is not None:
        params["success"] = success
    return await _proxy_get("/api/v1/history", params=params)


@router.get("/history/stats")
async def get_history_stats():
    """Proxy decision history statistics."""
    return await _proxy_get("/api/v1/history/stats")


@router.get("/history/{observation_id}")
async def get_history_observation(observation_id: str):
    """Proxy specific observation details by UUID."""
    return await _proxy_get(f"/api/v1/history/{observation_id}")


@router.get("/intelligence/summary")
async def get_intelligence_summary(
    window: Optional[str] = Query(default=None),
    start_time: Optional[str] = Query(default=None),
    end_time: Optional[str] = Query(default=None),
):
    """Proxy historical intelligence statistical summary."""
    params: Dict[str, Any] = {}
    if window:
        params["window"] = window
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    return await _proxy_get("/api/v1/intelligence/history/summary", params=params)


@router.get("/intelligence/trends")
async def get_intelligence_trends(
    window: Optional[str] = Query(default="1h"),
    start_time: Optional[str] = Query(default=None),
    end_time: Optional[str] = Query(default=None),
    bucket_seconds: Optional[int] = Query(default=None),
):
    """Proxy historical trend time-bucketed series."""
    params: Dict[str, Any] = {}
    if window:
        params["window"] = window
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    if bucket_seconds:
        params["bucket_seconds"] = bucket_seconds
    return await _proxy_get("/api/v1/intelligence/history/trends", params=params)


@router.get("/intelligence/divergence")
async def get_intelligence_divergence(
    window: Optional[str] = Query(default="1h"),
    start_time: Optional[str] = Query(default=None),
    end_time: Optional[str] = Query(default=None),
):
    """Proxy historical HPA divergence metrics."""
    params: Dict[str, Any] = {}
    if window:
        params["window"] = window
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    return await _proxy_get("/api/v1/intelligence/history/divergence", params=params)


@router.get("/intelligence/anomalies")
async def get_intelligence_anomalies(
    window: Optional[str] = Query(default="1h"),
    start_time: Optional[str] = Query(default=None),
    end_time: Optional[str] = Query(default=None),
    observation_id: Optional[str] = Query(default=None),
):
    """Proxy real-time anomaly intelligence assessment against historical baselines."""
    params: Dict[str, Any] = {}
    if window:
        params["window"] = window
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    if observation_id:
        params["observation_id"] = observation_id
    return await _proxy_get("/api/v1/intelligence/anomalies", params=params)


@router.post("/decision/orchestrate")
async def orchestrate_decision(request: Request):
    """
    Proxy operator manual decision orchestration request.
    Executes real Platform orchestration in dry-run / shadow mode.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {"namespace": settings.DEFAULT_NAMESPACE, "workload": settings.DEFAULT_WORKLOAD}
    return await _proxy_post("/api/v1/decision/orchestrate", payload=payload)


@router.post("/decision/aggregate")
async def aggregate_decision_context(request: Request):
    """
    Proxy decision context aggregation request (read-only assembly of M1+M2+M3).
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {"namespace": settings.DEFAULT_NAMESPACE, "workload": settings.DEFAULT_WORKLOAD}
    return await _proxy_post("/api/v1/decision/aggregate", payload=payload)
