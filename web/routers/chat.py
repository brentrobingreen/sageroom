import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..db import get_supabase
from ..limiter import limiter
from ..models import ChatRequest, ConversationOut, MessageOut
from ..services.billing_service import (
    can_use_free_tier,
    increment_free_messages,
    is_subscriber,
)
from ..services.brain_service import get_brain_or_404
from ..services.chat_service import stream_chat
from .auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/conversations", response_model=list[ConversationOut])
@limiter.limit("60/minute")
async def list_conversations(request: Request, current_user: dict = Depends(get_current_user)) -> list[ConversationOut]:
    db = await get_supabase()
    result = await db.table("conversations").select("id,brain_slug,title,created_at,last_message_at").eq("user_id", current_user["id"]).order("last_message_at", desc=True).execute()
    return [ConversationOut(**row) for row in result.data]


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
@limiter.limit("60/minute")
async def list_messages(request: Request, conversation_id: UUID, current_user: dict = Depends(get_current_user)) -> list[MessageOut]:
    db = await get_supabase()
    conv = await db.table("conversations").select("id").eq("id", str(conversation_id)).eq("user_id", current_user["id"]).execute()
    if not conv.data:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    result = await db.table("messages").select("id,role,content,created_at").eq("conversation_id", str(conversation_id)).order("created_at", desc=False).execute()
    return [MessageOut(**row) for row in result.data]


@router.delete("/conversations/{conversation_id}")
@limiter.limit("30/minute")
async def delete_conversation(request: Request, conversation_id: UUID, current_user: dict = Depends(get_current_user)) -> dict:
    db = await get_supabase()
    result = await db.table("conversations").delete().eq("id", str(conversation_id)).eq("user_id", current_user["id"]).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"ok": True}


@router.post("/chat/stream")
@limiter.limit("20/minute")
async def chat_stream(request: Request, body: ChatRequest, current_user: dict = Depends(get_current_user)) -> StreamingResponse:
    user_id = current_user["id"]
    brain = await get_brain_or_404(body.brain_slug)

    subscribed = await is_subscriber(user_id)
    if not subscribed:
        if not await can_use_free_tier(user_id):
            raise HTTPException(
                status_code=402,
                detail="You've used your 10 free messages. Subscribe to continue chatting.",
            )
        await increment_free_messages(user_id)

    return StreamingResponse(
        stream_chat(user_id, brain, body.message, body.conversation_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
