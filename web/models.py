from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator


class ChatRequest(BaseModel):
    brain_slug: str
    message: str
    conversation_id: UUID | None = None

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message cannot be empty")
        if len(v) > 2000:
            raise ValueError("message cannot exceed 2000 characters")
        return v


class GroupChatRequest(BaseModel):
    brain_slugs: list[str]
    question: str

    @field_validator("brain_slugs")
    @classmethod
    def validate_brain_count(cls, v: list[str]) -> list[str]:
        if len(v) < 2 or len(v) > 4:
            raise ValueError("group chat requires between 2 and 4 brains")
        if len(v) != len(set(v)):
            raise ValueError("duplicate brains are not allowed")
        return v

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question cannot be empty")
        if len(v) > 2000:
            raise ValueError("question cannot exceed 2000 characters")
        return v


class ConversationOut(BaseModel):
    id: UUID
    brain_slug: str
    title: str | None
    created_at: datetime
    last_message_at: datetime


class MessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime


class BrainOut(BaseModel):
    id: UUID
    slug: str
    display_name: str
    tagline: str | None
    category: str | None
    avatar_url: str | None


class SubscriptionStatusOut(BaseModel):
    status: str
    current_period_end: datetime | None
    free_messages_used: int
    monthly_cost_usd: float


class UsageStatsOut(BaseModel):
    monthly_cost_usd: float
    messages_sent: int
    group_sessions_count: int
