"""Available analysis-model endpoints."""

from fastapi import APIRouter, Depends

from app.schemas.model import SelectableModel
from app.services.llm_service import get_model_registry
from packages.llm_gateway.registry import ModelRegistry

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[SelectableModel])
def available_models(registry: ModelRegistry = Depends(get_model_registry)):
    return registry.available()
