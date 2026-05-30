import logging

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..db import get_supabase

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization token.")

    token = credentials.credentials
    try:
        db = await get_supabase()
        response = await db.auth.get_user(token)
        if not response.user:
            raise HTTPException(status_code=401, detail="Invalid or expired token.")
        user = response.user
        request.state.user_id = str(user.id)
        return {"id": str(user.id), "email": user.email}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Auth failure: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
