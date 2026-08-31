from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.endpoints import router as v1_router
from app.logging import StructuredLoggingMiddleware

app = FastAPI(
    title="SentinelScale — Demo E-Commerce API",
    description="Realistic cloud API generating business telemetry and workloads for SentinelScale evaluation.",
    version="0.1.0",
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
    return {"status": "ok", "service": "demo-api"}


@app.get("/ready", tags=["System"])
async def ready():
    return {"status": "ready", "service": "demo-api"}


@app.get("/version", tags=["System"])
async def version():
    return {
        "service": "demo-api",
        "service_version": "0.1.0",
        "environment": "development"
    }


# Attach product catalog and user business endpoints under root & versioned
app.include_router(v1_router)
app.include_router(v1_router, prefix="/api/v1")
