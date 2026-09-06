import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.proxy import router as proxy_router
from app.config import settings


STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="SentinelScale — Control Center",
    description="Custom Operator Control Center for SentinelScale Intelligent Security-Aware Autoscaling.",
    version=settings.SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(proxy_router)

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def get_index():
    """Serves the Control Center SPA dashboard."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "SentinelScale Control Center static assets not found."}


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
        "environment": settings.ENVIRONMENT,
        "platform_url": settings.PLATFORM_URL,
    }
