import asyncio
import json
from fastapi.responses import StreamingResponse
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.database_connection import get_db
from app.services.ai_client_services import AiClientService

ai_client = AiClientService()

strm_route = APIRouter()


@strm_route.post("/stream-fix")
async def stream_fix(payload: dict = Body(...)):
    """
    Stream assistant response for given messages.
    Expected JSON body:
    {
        "messages": [
            {"role": "user", "content": "Hello"}
        ]
    }
    """
    messages = payload.get("messages", [])
    if not messages:
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Write a short poem."},
        ]

    async def event_generator():
        async for delta in ai_client._groq_chat_stream(
            messages, model="llama-3.1-8b-instant", temperature=0.2, timeout=120
        ):
            # yield raw token text (fetch streaming reads directly)
            yield delta

    return StreamingResponse(event_generator(), media_type="text/plain")
