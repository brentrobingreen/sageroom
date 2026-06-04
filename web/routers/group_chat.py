import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..db import get_supabase
from ..limiter import limiter
from ..models import GroupChatRequest
from ..brain_registry import BRAIN_REGISTRY
from ..services.billing_service import check_and_deduct_access
from ..services.group_chat_service import (
    assess_context, save_context_answer, stream_deliberation
)
from .auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["group-chat"])


class ContextAnswerRequest(BaseModel):
    answer: str


class FollowUpRequest(BaseModel):
    question: str


@router.get("/group-sessions")
@limiter.limit("30/minute")
async def list_group_sessions(request: Request, current_user: dict = Depends(get_current_user)) -> list[dict]:
    db = await get_supabase()
    result = await db.table("group_sessions").select(
        "id,brain_slugs,question,status,created_at,completed_at"
    ).eq("user_id", current_user["id"]).order("created_at", desc=True).execute()
    return result.data


@router.get("/group-sessions/{session_id}")
@limiter.limit("60/minute")
async def get_group_session(request: Request, session_id: UUID, current_user: dict = Depends(get_current_user)) -> dict:
    db = await get_supabase()
    session = await db.table("group_sessions").select("*").eq("id", str(session_id)).eq("user_id", current_user["id"]).execute()
    if not session.data:
        raise HTTPException(status_code=404, detail="Session not found.")
    messages = await db.table("group_messages").select("*").eq("session_id", str(session_id)).order("created_at").execute()
    synthesis = await db.table("group_synthesis").select("content,created_at").eq("session_id", str(session_id)).execute()
    return {
        **session.data[0],
        "messages": messages.data,
        "synthesis": synthesis.data[0] if synthesis.data else None,
    }


@router.post("/group-chat")
@limiter.limit("5/minute")
async def create_group_session(
    request: Request,
    body: GroupChatRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    user_id = current_user["id"]

    await check_and_deduct_access(user_id)

    unknown = [s for s in body.brain_slugs if s not in BRAIN_REGISTRY]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown brain(s): {', '.join(unknown)}")

    daily_limit = int(os.environ.get("MAX_DAILY_GROUP_SESSIONS", "5"))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db = await get_supabase()
    count = await db.table("group_sessions").select("id", count="exact").eq("user_id", user_id).gte("created_at", today).execute()
    if (count.count or 0) >= daily_limit:
        raise HTTPException(status_code=429, detail=f"You've reached your limit of {daily_limit} sessions today.")

    result = await db.table("group_sessions").insert({
        "user_id": user_id,
        "brain_slugs": body.brain_slugs,
        "question": body.question,
        "status": "pending",
    }).execute()
    session_id = result.data[0]["id"]

    # Initial context assessment
    assessment = await assess_context(session_id)
    return {"session_id": session_id, **assessment}


@router.post("/group-chat/{session_id}/context")
@limiter.limit("20/minute")
async def submit_context_answer(
    request: Request,
    session_id: UUID,
    body: ContextAnswerRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    db = await get_supabase()
    session = await db.table("group_sessions").select("id").eq("id", str(session_id)).eq("user_id", current_user["id"]).execute()
    if not session.data:
        raise HTTPException(status_code=404, detail="Session not found.")

    await save_context_answer(str(session_id), body.answer)
    assessment = await assess_context(str(session_id))
    return assessment


@router.post("/group-chat/{session_id}/deliberate")
@limiter.limit("10/minute")
async def deliberate(
    request: Request,
    session_id: UUID,
    current_user: dict = Depends(get_current_user),
) -> StreamingResponse:
    db = await get_supabase()
    session = await db.table("group_sessions").select("brain_slugs").eq("id", str(session_id)).eq("user_id", current_user["id"]).execute()
    if not session.data:
        raise HTTPException(status_code=404, detail="Session not found.")

    return StreamingResponse(
        stream_deliberation(str(session_id), current_user["id"], session.data[0]["brain_slugs"]),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/group-chat/{session_id}/followup")
@limiter.limit("20/minute")
async def follow_up(
    request: Request,
    session_id: UUID,
    body: FollowUpRequest,
    current_user: dict = Depends(get_current_user),
) -> StreamingResponse:
    db = await get_supabase()
    session = await db.table("group_sessions").select("brain_slugs").eq("id", str(session_id)).eq("user_id", current_user["id"]).execute()
    if not session.data:
        raise HTTPException(status_code=404, detail="Session not found.")

    return StreamingResponse(
        stream_deliberation(str(session_id), current_user["id"], session.data[0]["brain_slugs"], follow_up=body.question),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
