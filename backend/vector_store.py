"""
Supabase pgvector adapter.

Reads/writes chunks to a Postgres table via the Supabase REST API. Retrieval
is performed by an RPC (`match_chunks`) defined in `migrations/0001_init.sql`.
"""

from __future__ import annotations

import logging
from typing import Any

from database import get_supabase

logger = logging.getLogger("chatpdf.vector_store")

CHUNKS_TABLE = "chunks"
MATCH_RPC = "match_chunks"


def _vector_to_pg(vector: list[float]) -> str:
    """pgvector accepts text in '[v1,v2,...]' form via PostgREST."""
    return "[" + ",".join(f"{v:.7f}" for v in vector) + "]"


def insert_chunks(rows: list[dict[str, Any]]) -> None:
    """Bulk-insert chunk rows. Embeddings should be plain Python lists."""
    if not rows:
        return

    payload = []
    for r in rows:
        payload.append(
            {
                "user_id": r["user_id"],
                "pdf_id": r["pdf_id"],
                "chunk_index": r["chunk_index"],
                "page": r["page"],
                "page_width": r["page_width"],
                "page_height": r["page_height"],
                "bbox": r["bbox"],
                "text": r["text"],
                "embedding": _vector_to_pg(r["embedding"]),
            }
        )

    supabase = get_supabase()
    # PostgREST imposes a row-count cap per request; chunk into batches of 200.
    BATCH = 200
    for i in range(0, len(payload), BATCH):
        batch = payload[i : i + BATCH]
        resp = supabase.table(CHUNKS_TABLE).insert(batch).execute()
        if getattr(resp, "error", None):
            raise RuntimeError(f"Supabase insert failed: {resp.error}")


def match_chunks(
    query_embedding: list[float],
    user_id: str,
    pdf_id: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Top-k nearest neighbours via the pgvector RPC."""
    supabase = get_supabase()
    resp = supabase.rpc(
        MATCH_RPC,
        {
            "query_embedding": _vector_to_pg(query_embedding),
            "p_user_id": user_id,
            "p_pdf_id": pdf_id,
            "match_count": top_k,
        },
    ).execute()
    if getattr(resp, "error", None):
        raise RuntimeError(f"Supabase RPC failed: {resp.error}")
    return resp.data or []


def delete_pdf_chunks(user_id: str, pdf_id: str) -> int:
    """Remove all chunks for a PDF — called on PDF deletion."""
    supabase = get_supabase()
    resp = (
        supabase.table(CHUNKS_TABLE)
        .delete()
        .eq("user_id", user_id)
        .eq("pdf_id", pdf_id)
        .execute()
    )
    if getattr(resp, "error", None):
        raise RuntimeError(f"Supabase delete failed: {resp.error}")
    return len(resp.data or [])
