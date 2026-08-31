from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.endpoints import router as v1_router
from app.config.settings import settings
from app.logging import StructuredLoggingMiddleware

app = FastAPI(
    title="SentinelScale — Platform & Decision Service",
    description="Module 3: Resource state observation, baseline HPA comparison, and policy-guarded decision engine.",
    version=settings.SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(StructuredLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}


@app.get("/ready", tags=["System"])
async def ready():
    return {"status": "ready", "service": settings.SERVICE_NAME}


@app.get("/version", tags=["System"])
async def version():
    return {
        "service": settings.SERVICE_NAME,
        "service_version": settings.SERVICE_VERSION,
        "contract_version": settings.CONTRACT_VERSION,
        "model_version": settings.MODEL_VERSION,
        "environment": settings.ENVIRONMENT,
        "dry_run": settings.SENTINEL_DRY_RUN,
        "shadow_mode": settings.SENTINEL_SHADOW_MODE,
        "autonomous_actions_enabled": settings.SENTINEL_AUTONOMOUS_ACTIONS_ENABLED,
    }


app.include_router(v1_router, prefix="/api/v1")
