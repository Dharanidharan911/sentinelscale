import json
import logging
import time
import uuid
from datetime import datetime, timezone
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": getattr(record, "service", "platform"),
            "message": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "trace_id"):
            log_data["trace_id"] = record.trace_id
        if hasattr(record, "endpoint"):
            log_data["endpoint"] = record.endpoint
        if hasattr(record, "latency_ms"):
            log_data["latency_ms"] = record.latency_ms
        if hasattr(record, "status_code"):
            log_data["status_code"] = record.status_code
        return json.dumps(log_data)


def setup_logger(service_name: str, log_level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(service_name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger


logger = setup_logger("platform")


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        trace_id = request.headers.get("X-Trace-ID", f"trace-{uuid.uuid4().hex[:16]}")
        start_time = time.perf_counter()

        response: Response = await call_next(request)
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id

        logger.info(
            f"{request.method} {request.url.path} completed with {response.status_code} in {latency_ms}ms",
            extra={
                "service": "platform",
                "request_id": request_id,
                "trace_id": trace_id,
                "endpoint": request.url.path,
                "latency_ms": latency_ms,
                "status_code": response.status_code,
            }
        )
        return response
