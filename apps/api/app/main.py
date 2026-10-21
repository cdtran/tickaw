"""HTTP entry point for the local development API."""

from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.v1.router import router
from app.core.observability import event, request_id, route_label

app = FastAPI(
    title="tickaw API",
    version="0.1.0",
    description="Local development API for the tickaw platform.",
)


@app.middleware("http")
async def private_api_responses(request, call_next):
    correlation = str(uuid4())
    context = request_id.set(correlation)
    started = perf_counter()
    try:
        try:
            response = await call_next(request)
        except Exception as error:  # noqa: BLE001 -- do not expose raw server errors or SQL parameters.
            event("operation.failed", operation="http", exception_type=type(error).__name__)
            response = JSONResponse({"detail": "An internal error occurred."}, status_code=500)
        response.headers["X-Request-ID"] = correlation
        event(
            "http.completed",
            method=request.method,
            status_code=response.status_code,
            route=route_label(request.url.path),
            duration_ms=(perf_counter() - started) * 1000,
        )
    finally:
        request_id.reset(context)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
    return response


app.include_router(router)


@app.get("/health", tags=["platform"])
def health_check() -> dict[str, str]:
    """Return process health; dependency checks arrive with their integrations."""
    return {"status": "ok", "service": "api"}
