import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from ..db import get_supabase
from ..limiter import limiter
from ..models import GroupChatRequest
from ..brain_registry import BRAIN_REGISTRY
from ..services.billing_service import is_subscriber
from ..services.group_chat_service import run_group_chat
from .auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["group-chat"])


@router.get("/group-sessions")
@limiter.limit("30/minute")
async def list_group_sessions(request: Request, current_user: dict = Depends(get_current_user)) -> list[dict]:
    db = await get_supabase()
    result = await db.table("group_sessions").select("id,brain_slugs,question,status,created_at,completed_at").eq("user_id", current_user["id"]).order("created_at", desc=True).execute()
    return result.data


@router.get("/group-sessions/{session_id}")
@limiter.limit("60/minute")
async def get_group_session(request: Request, session_id: UUID, current_user: dict = Depends(get_current_user)) -> dict:
    db = await get_supabase()
    session = await db.table("group_sessions").select("*").eq("id", str(session_id)).eq("user_id", current_user["id"]).execute()
    if not session.data:
        raise HTTPException(status_code=404, detail="Session not found.")

    responses = await db.table("group_responses").select("brain_slug,round,content,created_at").eq("session_id", str(session_id)).order("round,created_at").execute()
    synthesis = await db.table("group_synthesis").select("content,created_at").eq("session_id", str(session_id)).execute()

    return {
        **session.data[0],
        "responses": responses.data,
        "synthesis": synthesis.data[0] if synthesis.data else None,
    }


@router.get("/group-chat/{session_id}/status")
@limiter.limit("60/minute")
async def group_chat_status(request: Request, session_id: UUID, current_user: dict = Depends(get_current_user)) -> dict:
    db = await get_supabase()
    result = await db.table("group_sessions").select("id,status,completed_at").eq("id", str(session_id)).eq("user_id", current_user["id"]).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Session not found.")
    return result.data[0]


@router.post("/group-chat")
@limiter.limit("5/minute")
async def start_group_chat(
    request: Request,
    body: GroupChatRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
) -> dict:
    user_id = current_user["id"]

    if not await is_subscriber(user_id):
        raise HTTPException(status_code=402, detail="Group chat requires an active subscription.")

    # Validate all requested brains exist in registry
    unknown = [s for s in body.brain_slugs if s not in BRAIN_REGISTRY]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown brain(s): {', '.join(unknown)}")

    # Enforce daily session cap
    daily_limit = int(os.environ.get("MAX_DAILY_GROUP_SESSIONS", "2"))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db = await get_supabase()
    count_result = await db.table("group_sessions").select("id", count="exact").eq("user_id", user_id).gte("created_at", today).execute()
    if (count_result.count or 0) >= daily_limit:
        raise HTTPException(status_code=429, detail=f"You've reached your limit of {daily_limit} group sessions today. Come back tomorrow.")

    # Create session record
    session_result = await db.table("group_sessions").insert({
        "user_id": user_id,
        "brain_slugs": body.brain_slugs,
        "question": body.question,
        "status": "pending",
    }).execute()
    session_id = session_result.data[0]["id"]

    background_tasks.add_task(run_group_chat, session_id, user_id, body.brain_slugs, body.question)

    return {"session_id": session_id, "status": "pending"}
