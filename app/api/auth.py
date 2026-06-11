from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.schemas import TokenRequest, TokenResponse
from app.core.auth import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

# In a real deployment this would look up the key in a DB / KMS.
# For the demo we accept any non-empty key and embed it as the subject.
_DEMO_FORBIDDEN = {"", "null", "undefined"}


@router.post("/token", response_model=TokenResponse)
def issue_token(req: TokenRequest) -> TokenResponse:
    if req.api_key.strip() in _DEMO_FORBIDDEN:
        raise HTTPException(status_code=400, detail="api_key required")
    token = create_access_token(subject=req.api_key)
    return TokenResponse(access_token=token)
