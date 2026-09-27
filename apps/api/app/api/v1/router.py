from fastapi import APIRouter

from app.api.v1.endpoints.datasets import router as datasets_router

router = APIRouter(prefix="/api/v1")
router.include_router(datasets_router)

from app.api.v1.endpoints.notebooks import router as notebooks_router
router.include_router(notebooks_router)

from app.api.v1.endpoints.analyses import router as analyses_router
router.include_router(analyses_router)
