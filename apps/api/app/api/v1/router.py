from fastapi import APIRouter

from app.api.v1.endpoints.datasets import router as datasets_router

router = APIRouter(prefix="/api/v1")
router.include_router(datasets_router)
