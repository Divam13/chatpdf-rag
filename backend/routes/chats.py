"""
Chat routes: CRUD for chats + RAG-grounded message handling.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from chat_engine import answer_question
from database import chats_col, pdfs_col
from models import (
    ChatListItem,
    ChatOut,
    Citation,
    MessageOut,
    RenameChatRequest,
    SendMessageRequest,
)

logger = logging.getLogger("chatpdf.chats")

router = APIRouter(prefix="/api/chats", tags=["chats"])


def _to_message_out(m: dict) -> MessageOut:
    return MessageOut(
        role=m["role"],
        content=m["content"],
        citations=[Citation(**c) for c in m.get("citations", [])],
        timestamp=m["timestamp"],
    )


@router.post("/", response_model=ChatOut, status_code=201)
async def create_chat(
    pdf_id: str,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["_id"]
    pdf_doc = await pdfs_col().find_one({"_id": ObjectId(pdf_id), "user_id": user_id})
    if not pdf_doc:
        raise HTTPException(status_code=404, detail="PDF not found")

    now = datetime.now(timezone.utc)
    chat_doc = {
        "user_id": user_id,
        "pdf_id": pdf_id,
        "pdf_filename": pdf_doc["filename"],
        "title": f"Chat with {pdf_doc['filename']}",
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    result = await chats_col().insert_one(chat_doc)
    chat_id = str(result.inserted_id)
    logger.info(f"[CREATE_CHAT] chat_id={chat_id} pdf={pdf_doc['filename']}")

    return ChatOut(
        id=chat_id,
        pdf_id=pdf_id,
        pdf_filename=pdf_doc["filename"],
        title=chat_doc["title"],
        messages=[],
        created_at=now,
        updated_at=now,
    )


@router.get("/", response_model=list[ChatListItem])
async def list_chats(current_user: dict = Depends(get_current_user)):
    user_id = current_user["_id"]
    cursor = chats_col().find({"user_id": user_id}).sort("updated_at", -1)
    return [
        ChatListItem(
            id=str(doc["_id"]),
            pdf_id=doc["pdf_id"],
            pdf_filename=doc.get("pdf_filename", "Unknown"),
            title=doc["title"],
            message_count=len(doc.get("messages", [])),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )
        async for doc in cursor
    ]


@router.get("/{chat_id}", response_model=ChatOut)
async def get_chat(chat_id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user["_id"]
    doc = await chats_col().find_one({"_id": ObjectId(chat_id), "user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Chat not found")

    return ChatOut(
        id=str(doc["_id"]),
        pdf_id=doc["pdf_id"],
        pdf_filename=doc.get("pdf_filename", "Unknown"),
        title=doc["title"],
        messages=[_to_message_out(m) for m in doc.get("messages", [])],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


@router.delete("/{chat_id}", status_code=204)
async def delete_chat(chat_id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user["_id"]
    result = await chats_col().delete_one(
        {"_id": ObjectId(chat_id), "user_id": user_id}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Chat not found")


@router.patch("/{chat_id}", response_model=ChatOut)
async def rename_chat(
    chat_id: str,
    body: RenameChatRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["_id"]
    result = await chats_col().find_one_and_update(
        {"_id": ObjectId(chat_id), "user_id": user_id},
        {"$set": {"title": body.title, "updated_at": datetime.now(timezone.utc)}},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Chat not found")

    return ChatOut(
        id=str(result["_id"]),
        pdf_id=result["pdf_id"],
        pdf_filename=result.get("pdf_filename", "Unknown"),
        title=result["title"],
        messages=[_to_message_out(m) for m in result.get("messages", [])],
        created_at=result["created_at"],
        updated_at=result["updated_at"],
    )


@router.post("/{chat_id}/message", response_model=ChatOut)
async def send_message(
    chat_id: str,
    body: SendMessageRequest,
    current_user: dict = Depends(get_current_user),
):
    total_start = time.time()
    user_id = current_user["_id"]
    logger.info(f"[SEND_MSG] ▶ chat={chat_id} q={body.content[:80]!r}")

    chat_doc = await chats_col().find_one(
        {"_id": ObjectId(chat_id), "user_id": user_id}
    )
    if not chat_doc:
        raise HTTPException(status_code=404, detail="Chat not found")

    pdf_doc = await pdfs_col().find_one(
        {"_id": ObjectId(chat_doc["pdf_id"]), "user_id": user_id}
    )
    if not pdf_doc:
        raise HTTPException(status_code=404, detail="PDF not found")

    existing_messages = chat_doc.get("messages", [])

    history = [
        {"role": m["role"], "content": m["content"]} for m in existing_messages
    ]

    try:
        result = await asyncio.to_thread(
            answer_question,
            body.content,
            user_id,
            chat_doc["pdf_id"],
            history,
        )
        ai_content = result["answer"]
        citations = result["citations"]
    except Exception as e:
        logger.exception(f"[SEND_MSG] RAG failed: {e}")
        ai_content = "Sorry — I hit an error while answering. Please try again."
        citations = []

    now = datetime.now(timezone.utc)
    user_msg = {
        "role": "user",
        "content": body.content,
        "citations": [],
        "timestamp": now,
    }
    assistant_msg = {
        "role": "assistant",
        "content": ai_content,
        "citations": citations,
        "timestamp": datetime.now(timezone.utc),
    }

    update_fields: dict = {"updated_at": datetime.now(timezone.utc)}
    if len(existing_messages) == 0:
        new_title = body.content[:50] + ("…" if len(body.content) > 50 else "")
        update_fields["title"] = new_title

    await chats_col().update_one(
        {"_id": ObjectId(chat_id)},
        {
            "$push": {"messages": {"$each": [user_msg, assistant_msg]}},
            "$set": update_fields,
        },
    )

    updated = await chats_col().find_one({"_id": ObjectId(chat_id)})
    logger.info(f"[SEND_MSG] ✅ done chat={chat_id} in {time.time()-total_start:.2f}s")

    return ChatOut(
        id=str(updated["_id"]),
        pdf_id=updated["pdf_id"],
        pdf_filename=updated.get("pdf_filename", "Unknown"),
        title=updated["title"],
        messages=[_to_message_out(m) for m in updated.get("messages", [])],
        created_at=updated["created_at"],
        updated_at=updated["updated_at"],
    )
