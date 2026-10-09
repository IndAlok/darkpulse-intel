from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from darkpulse.api.deps import SettingsDep
from darkpulse.api.security import (
    ViewerDep,
    configured_principal,
    mint_session,
    revoke_session,
)
from darkpulse.models import ApiEnvelope

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=4096)


@router.post("/login", response_model=ApiEnvelope)
async def login(req: LoginRequest, settings: SettingsDep) -> dict[str, Any]:
    principal = configured_principal(req.token, settings)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token"
        )
    return {
        "data": {
            "subject": principal.subject,
            "role": principal.role,
            "token": mint_session(principal, req.token),
        },
        "meta": {},
    }


@router.post("/logout", response_model=ApiEnvelope)
async def logout(
    principal: ViewerDep,
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
) -> dict[str, Any]:
    if credentials is not None:
        revoke_session(credentials.credentials)
    return {"data": {"subject": principal.subject, "role": principal.role}, "meta": {}}


@router.post("/refresh", response_model=ApiEnvelope)
async def refresh(
    principal: ViewerDep,
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required"
        )
    revoke_session(credentials.credentials)
    session = mint_session(principal, credentials.credentials)
    return {
        "data": {"subject": principal.subject, "role": principal.role, "token": session},
        "meta": {},
    }


@router.get("/me", response_model=ApiEnvelope)
async def me(principal: ViewerDep) -> dict[str, Any]:
    return {"data": {"subject": principal.subject, "role": principal.role}, "meta": {}}
