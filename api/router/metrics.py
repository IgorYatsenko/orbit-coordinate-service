from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST

from api.dependencies import get_services
from api.services import Services

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
def metrics(services: Annotated[Services, Depends(get_services)]) -> Response:
    if services.metrics is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return Response(services.metrics.collect(), headers={"Content-Type": CONTENT_TYPE_LATEST})
