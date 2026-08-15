from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from darkpulse.api.deps import SettingsDep
from darkpulse.api.security import ViewerDep, websocket_principal
from darkpulse.models import ApiEnvelope

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=4096)


@router.post("/login", response_model=ApiEnvelope)
async def login(req: LoginRequest, settings: SettingsDep) -> dict[str, Any]:
    principal = websocket_principal(req.token, settings)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token"
        )
    return {
        "data": {"subject": principal.subject, "role": principal.role, "token": req.token},
        "meta": {},
    }


@router.get("/me", response_model=ApiEnvelope)
async def me(principal: ViewerDep) -> dict[str, Any]:
    return {"data": {"subject": principal.subject, "role": principal.role}, "meta": {}}
