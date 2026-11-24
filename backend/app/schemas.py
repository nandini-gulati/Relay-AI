"""Pydantic schemas matching the exact contract in sections 3-5 of the assignment."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class HealthResponse(BaseModel):
    status: str = "ok"
    keys_configured: int
    cache_enabled: bool = True


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(...)
    system_prompt: Optional[str] = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("message must be a string")
        trimmed = v.strip()
        if len(trimmed) < 1:
            raise ValueError("message cannot be empty or whitespace-only")
        if len(trimmed) > 4000:
            raise ValueError("message exceeds maximum length of 4000 characters after trimming")
        return trimmed

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("session_id must be a string")
        trimmed = v.strip()
        if len(trimmed) < 1 or len(trimmed) > 128:
            raise ValueError("session_id length must be between 1 and 128 characters")
        return trimmed


class ChatMetadata(BaseModel):
    resolution_source: Literal["LIVE_INFERENCE", "LLM_CACHE"]
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: Optional[str] = None
    fallback_attempts: int


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: ChatMetadata


class MessageMetadata(BaseModel):
    resolution_source: str
    input_tokens: int
    output_tokens: int


class MessageItem(BaseModel):
    role: str
    content: str
    metadata: Optional[MessageMetadata] = None


class SessionHistoryResponse(BaseModel):
    session_id: str
    messages: List[MessageItem]


class ErrorDetail(BaseModel):
    detail: Any
