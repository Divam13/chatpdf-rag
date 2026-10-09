"""
RAG orchestration: embed query → retrieve from pgvector → ground with Gemini →
attach citation metadata so the frontend can highlight bboxes in the PDF.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from gemini_client import condense_question, embed_query, generate_grounded_answer
from vector_store import match_chunks

logger = logging.getLogger("chatpdf.engine")

TOP_K = 5

# Exact refusal phrase mandated by the system prompt. Used to suppress citations
# on legitimate "not found" answers.
REFUSAL = "I could not find that in the document."

# Match citations the model produces, e.g. [1], [2,3], [4, 5].
_CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def _used_indices(answer: str, ctx_len: int) -> list[int]:
    """Pull citation indices the model actually used in its answer."""
    seen: list[int] = []
    for match in _CITE_RE.finditer(answer):
        for token in match.group(1).split(","):
            token = token.strip()
            if token.isdigit():
                idx = int(token)
                if 1 <= idx <= ctx_len and idx not in seen:
                    seen.append(idx)
    return seen


def answer_question(
    question: str,
    user_id: str,
    pdf_id: str,
    history: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Run one RAG turn. Returns:
      {
        "answer": str,
        "citations": [
            {
              "label": "p3#1",
              "page": 3,
              "bbox": [x0,y0,x1,y1],
              "page_width": 612.0,
              "page_height": 792.0,
              "snippet": "first ~240 chars of the chunk",
            }, ...
        ],
      }
    """
    t_start = time.time()
    logger.info(f"[CHAT] ▶ user={user_id} pdf={pdf_id} q={question[:80]!r}")

    # 1. Condense follow-up questions into standalone form for retrieval.
    #    The original question is still used for the final grounded prompt.
    t0 = time.time()
    retrieval_query = condense_question(question, history or [])
    logger.info(f"[CHAT] condensed in {time.time()-t0:.2f}s")

    # 2. Embed the retrieval query and pull top-k chunks.
    t0 = time.time()
    q_vec = embed_query(retrieval_query)
    logger.info(f"[CHAT] embedded query in {time.time()-t0:.2f}s")

    t0 = time.time()
    retrieved = match_chunks(q_vec, user_id=user_id, pdf_id=pdf_id, top_k=TOP_K)
    logger.info(f"[CHAT] retrieved {len(retrieved)} chunks in {time.time()-t0:.2f}s")

    if not retrieved:
        return {"answer": REFUSAL, "citations": []}

    # 3. Ground with Gemini using the original question wording.
    t0 = time.time()
    answer = generate_grounded_answer(question, retrieved, history=history)
    logger.info(f"[CHAT] gemini responded in {time.time()-t0:.2f}s")

    # 4. If the model legitimately refused, don't fake a citation.
    if REFUSAL in answer:
        logger.info("[CHAT] refusal detected — emitting no citations")
        return {"answer": REFUSAL, "citations": []}

    used = _used_indices(answer, len(retrieved))
    # Fallback: model answered but forgot to cite — surface the top-1 chunk so
    # the user still has a clickable source.
    if not used:
        used = [1]

    citations = []
    for idx in used:
        chunk = retrieved[idx - 1]
        snippet = chunk["text"].strip().replace("\n", " ")
        if len(snippet) > 240:
            snippet = snippet[:240].rstrip() + "…"
        citations.append(
            {
                "label": f"p{chunk['page']}#{chunk['chunk_index']}",
                "page": chunk["page"],
                "bbox": chunk["bbox"],
                "page_width": chunk["page_width"],
                "page_height": chunk["page_height"],
                "snippet": snippet,
            }
        )

    logger.info(
        f"[CHAT] ✅ done in {time.time()-t_start:.2f}s — {len(citations)} citations"
    )
    return {"answer": answer, "citations": citations}
