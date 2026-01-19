from fastapi import APIRouter, Depends, HTTPException, status
from google.auth.transport import requests
from google.oauth2 import id_token
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import TokenRequest, TokenResponse

router = APIRouter()
settings = get_settings()


def _unique_nickname(db: Session, base: str) -> str:
    base = (base or "user").strip() or "user"
    base = base[:50]
    candidate = base
    counter = 1
    while db.query(User).filter(User.nickname == candidate).first() is not None:
        suffix = f"_{counter}"
        candidate = f"{base[: 50 - len(suffix)]}{suffix}"
        counter += 1
    return candidate


@router.post("/auth/google", response_model=TokenResponse)
async def google_auth(payload: TokenRequest, db: Session = Depends(get_db)):
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GOOGLE_CLIENT_ID is not configured",
        )

    try:
        idinfo = id_token.verify_oauth2_token(
            payload.token, requests.Request(), settings.google_client_id
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid token")

    if idinfo.get("email_verified") is False:
        raise HTTPException(status_code=400, detail="Unverified email")

    google_sub = idinfo.get("sub")
    if not google_sub:
        raise HTTPException(status_code=400, detail="Invalid token payload")

    user = db.query(User).filter(User.google_id == google_sub).first()
    if not user:
        nickname = _unique_nickname(db, idinfo.get("name") or idinfo.get("email") or "")
        user = User(
            google_id=google_sub,
            email=idinfo.get("email"),
            nickname=nickname,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    token = create_access_token(data={"sub": str(user.id)})
    return TokenResponse(access_token=token)
