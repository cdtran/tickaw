from fastapi import APIRouter, Depends

from app.api.v1.endpoints.analyses import router as analyses_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.datasets import router as datasets_router
from app.api.v1.endpoints.models import router as models_router
from app.api.v1.endpoints.notebooks import router as notebooks_router
from app.services.auth_service import current_user

router = APIRouter(prefix="/api/v1")
for protected_router in (datasets_router, notebooks_router, analyses_router, models_router):
    router.include_router(protected_router, dependencies=[Depends(current_user)])
router.include_router(auth_router)
