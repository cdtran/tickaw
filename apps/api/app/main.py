"""HTTP entry point for the local development API."""

from fastapi import FastAPI

from app.api.v1.router import router


app = FastAPI(
    title="Data Notebook API",
    version="0.1.0",
    description="Local development API for the Data Notebook platform.",
)


app.include_router(router)


@app.get("/health", tags=["platform"])
def health_check() -> dict[str, str]:
    """Return process health; dependency checks arrive with their integrations."""
    return {"status": "ok", "service": "api"}
