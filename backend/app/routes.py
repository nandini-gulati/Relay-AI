"""FastAPI route handlers for health, chat completions, and session history."""

import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.auth import get_optional_user
from app.config import settings
from app.db import (
    check_db_reachable,
    delete_session,
    get_session_history_for_llm,
    get_session_messages_endpoint,
    insert_chat_turn,
    list_sessions,
    upsert_session,
)
from app.llm.exceptions import AllProvidersUnavailableException
from app.llm.service import execute_chat_completion
from app.schemas import (
    ChatMetadata,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    SessionHistoryResponse,
    SessionListResponse,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check():
    """Health check endpoint.

    Returns 200 only when the database is reachable and the key pool is loaded.
    """
    if not check_db_reachable():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unreachable",
        )

    keys_count = len(settings.KEY_POOL)
    return HealthResponse(
        status="ok",
        keys_configured=keys_count,
        cache_enabled=True,
    )


@router.post("/chat", response_model=ChatResponse)
def chat_endpoint(
    req: ChatRequest,
    x_simulate_failure: Optional[str] = Header(None, alias="X-Simulate-Failure"),
    current_user=Depends(get_optional_user),
):
    """Main chat completion endpoint.

    - Resolves system prompt (overriding for the session if provided).
    - Assembles message sequence: [system] + history + [new user message].
    - Executes LLM gateway call with failover and caching.
    - Atomically persists the turn upon success.
    - If failure occurs, records nothing to session history.
    """
    start_time = time.perf_counter()
    user_id = current_user["uid"] if current_user else None

    # 1. Resolve and persist system prompt for session (scoped to user)
    try:
        system_prompt = upsert_session(req.session_id, req.system_prompt, user_id=user_id)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this session",
        )

    # 2. Retrieve existing session history
    history = get_session_history_for_llm(req.session_id)

    # 3. Assemble full message list for LiteLLM
    full_messages = [{"role": "system", "content": system_prompt}]
    full_messages.extend(history)
    full_messages.append({"role": "user", "content": req.message})

    # 4. Execute completion across key pool with caching
    try:
        reply_text, metadata_dict = execute_chat_completion(
            messages=full_messages,
            simulate_header=x_simulate_failure,
        )
    except AllProvidersUnavailableException as e:
        # 503 when every key in key pool fails. Nothing is added to DB history.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=e.detail,
        )

    # 5. Measure server-side latency in milliseconds
    elapsed_ms = int(round((time.perf_counter() - start_time) * 1000))
    metadata_dict["latency_ms"] = max(1, elapsed_ms)

    # 6. Atomically persist user message and assistant reply to SQLite
    insert_chat_turn(
        session_id=req.session_id,
        user_content=req.message,
        assistant_content=reply_text,
        metadata_dict=metadata_dict,
    )

    # 7. Return contract-matching response
    chat_metadata = ChatMetadata(**metadata_dict)
    return ChatResponse(
        session_id=req.session_id,
        reply=reply_text,
        metadata=chat_metadata,
    )


@router.get("/sessions/{session_id}/messages", response_model=SessionHistoryResponse)
def get_session_messages(
    session_id: str,
    current_user=Depends(get_optional_user),
):
    """Retrieve message history for a specific session.

    Returns oldest first, excluding the system prompt.
    Returns 404 detail 'session not found' if the session does not exist or belongs to another user.
    """
    user_id = current_user["uid"] if current_user else None
    messages = get_session_messages_endpoint(session_id, user_id=user_id)
    if messages is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found",
        )

    return SessionHistoryResponse(
        session_id=session_id,
        messages=messages,
    )


@router.get("/sessions", response_model=SessionListResponse)
def get_sessions(current_user=Depends(get_optional_user)):
    """List saved chat sessions belonging strictly to the authenticated user."""
    user_id = current_user["uid"] if current_user else None
    return SessionListResponse(sessions=list_sessions(user_id=user_id))


@router.delete("/sessions/{session_id}")
def remove_session(session_id: str, current_user=Depends(get_optional_user)):
    """Delete a saved chat session belonging to the authenticated user."""
    user_id = current_user["uid"] if current_user else None
    deleted = delete_session(session_id, user_id=user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found",
        )
    return {"deleted": True, "session_id": session_id}
