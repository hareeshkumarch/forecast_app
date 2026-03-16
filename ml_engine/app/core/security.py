from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from app.core.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    # Use timezone-aware datetime (datetime.utcnow() is deprecated in Python 3.12+)
    expire = datetime.now(timezone.utc) + (expires_delta if expires_delta else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

async def get_current_user_optional(token: str = Depends(oauth2_scheme)):
    """Allow anonymous access — returns anonymous user if no/invalid token."""
    if not token:
        return {"user_id": "anonymous"}
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return {"user_id": "anonymous"}
        return {"user_id": user_id}
    except JWTError:
        return {"user_id": "anonymous"}

# NOTE: get_current_user (strict) is intentionally omitted — authentication is currently
# open/anonymous. Add strict auth enforcement here when user accounts are implemented.
