"""
Thin wrapper around the `google-genai` SDK (the successor to the now-deprecated
`google-generativeai` package). Two responsibilities:

  • embed_documents / embed_query  — gemini-embedding-001 (768-d, L2-normalized)
  • generate_grounded_answer       — gemini-2.5-flash chat with RAG context
"""

from __future__ import annotations

import logging
import math
import os
import random
import re
import time
from typing import Callable, Iterable, TypeVar

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

load_dotenv()

logger = logging.getLogger("chatpdf.gemini")

EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
CHAT_MODEL  = os.getenv("GEMINI_CHAT_MODEL", "gemini-2.5-flash")
# gemini-embedding-001 supports Matryoshka — request 768 to match our pgvector schema.
EMBED_DIM   = 768

_client: genai.Client | None = None


T = TypeVar("T")

_RETRY_AFTER_RE = re.compile(r"retry in (\d+(?:\.\d+)?)s", re.IGNORECASE)


def _retry_delay_from_error(err: Exception) -> float | None:
    """Pull the server-suggested retry delay out of a 429 message, if present."""
    m = _RETRY_AFTER_RE.search(str(err))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _with_retry(fn: Callable[[], T], op: str, max_attempts: int = 5) -> T:
    """
    Run `fn` with exponential backoff on 429 / 5xx.
    Honours the `retry in Ns` hint Gemini includes in 429 responses.
    """
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except genai_errors.ClientError as e:
            # 429 RESOURCE_EXHAUSTED — wait and retry. The SDK exposes the
            # HTTP status as `.code` (int); `.status` is the proto status name.
            code = getattr(e, "code", None)
            if code == 429 and attempt < max_attempts:
                hint = _retry_delay_from_error(e)
                # Server hint, capped at 30s; otherwise exponential backoff with jitter.
                wait = min(hint, 30) if hint else min(2 ** attempt + random.random(), 30)
                logger.warning(
                    f"[{op}] 429 from Gemini (attempt {attempt}/{max_attempts}); "
                    f"sleeping {wait:.1f}s"
                )
                time.sleep(wait)
                last_err = e
                continue
            raise
        except genai_errors.ServerError as e:
            if attempt < max_attempts:
                wait = min(2 ** attempt + random.random(), 30)
                logger.warning(
                    f"[{op}] {e} (attempt {attempt}/{max_attempts}); sleeping {wait:.1f}s"
                )
                time.sleep(wait)
                last_err = e
                continue
            raise
    assert last_err is not None
    raise last_err


def _l2_normalize(vec: list[float]) -> list[float]:
    """gemini-embedding-001 at <3072 dims requires L2 normalization for cosine similarity."""
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def _get_client() -> genai.Client:
    """Lazily build the SDK client. Accepts GEMINI_API_KEY or GOOGLE_API_KEY."""
    global _client
    if _client is None:
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise EnvironmentError("GEMINI_API_KEY is not set in the environment.")
        _client = genai.Client(api_key=key)
    return _client


def embed_documents(texts: Iterable[str]) -> list[list[float]]:
    """
    Embed a batch of passages for storage/retrieval.
    Uses task_type=RETRIEVAL_DOCUMENT which Gemini optimises for indexing.
    """
    texts = list(texts)
    if not texts:
        return []

    client = _get_client()
    out: list[list[float]] = []
    # gemini-embedding-001 free tier is ~5–100 RPM; 8 per call keeps token volume
    # low enough that TPM limits don't trip on long chunks.
    BATCH = 8
    for i in range(0, len(texts), BATCH):
        batch = texts[i : i + BATCH]

        def _call(b=batch):
            return client.models.embed_content(
                model=EMBED_MODEL,
                contents=b,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=EMBED_DIM,
                ),
            )

        resp = _with_retry(_call, op=f"embed_documents[{i}:{i+len(batch)}]")
        for emb in resp.embeddings:
            out.append(_l2_normalize(list(emb.values)))
    return out


def embed_query(text: str) -> list[float]:
    """Embed a single user query with task_type=RETRIEVAL_QUERY."""
    client = _get_client()
    resp = _with_retry(
        lambda: client.models.embed_content(
            model=EMBED_MODEL,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=EMBED_DIM,
            ),
        ),
        op="embed_query",
    )
    return _l2_normalize(list(resp.embeddings[0].values))


CONDENSE_INSTRUCTION = (
    "You rewrite a follow-up question into a standalone question that can be "
    "understood without the prior conversation. Resolve any pronoun or "
    'demonstrative reference ("it", "that", "this", "those", "those changes") '
    "using the conversation. Preserve every concrete noun and qualifier from "
    "the follow-up. If the follow-up is already self-contained, return it "
    "unchanged. Output exactly one line containing only the rewritten "
    "question. Do not add quotes, preface, explanation, or trailing punctuation "
    "beyond a single question mark."
)


CONDENSE_FEWSHOT = (
    "Example:\n"
    "Conversation so far:\n"
    "User: Summarize airport performance in H1-26.\n"
    "Assistant: Passenger traffic rose to 49.3M while cargo reached 0.62M MT.\n"
    "Follow-up: Break that down into passenger and cargo changes.\n"
    "Standalone: Break down airport performance in H1-26 into passenger and cargo changes.\n\n"
)


def condense_question(question: str, history: list[dict]) -> str:
    """
    Rewrite a follow-up into a standalone question so retrieval gets useful
    context. No-op when history is empty.
    """
    if not history:
        return question

    client = _get_client()

    # Build a compact transcript using only the last four turns — enough to
    # resolve references without wasting tokens.
    transcript_lines: list[str] = []
    for msg in history[-4:]:
        speaker = "User" if msg["role"] == "user" else "Assistant"
        transcript_lines.append(f"{speaker}: {msg['content']}")
    transcript = "\n".join(transcript_lines)

    prompt = (
        f"{CONDENSE_FEWSHOT}"
        "Now rewrite this:\n"
        f"Conversation so far:\n{transcript}\n"
        f"Follow-up: {question}\n"
        "Standalone:"
    )

    try:
        resp = _with_retry(
            lambda: client.models.generate_content(
                model=CHAT_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=CONDENSE_INSTRUCTION,
                    temperature=0.0,
                    max_output_tokens=512,
                ),
            ),
            op="condense_question",
        )
        condensed = (resp.text or "").strip().strip('"').strip("'").rstrip()
        # Strip a leading "Standalone:" or "Question:" if the model echoed it.
        for prefix in ("Standalone:", "Question:", "Q:"):
            if condensed.lower().startswith(prefix.lower()):
                condensed = condensed[len(prefix):].strip()
        if not condensed:
            return question
        logger.info(f"[CONDENSE] {question!r} -> {condensed!r}")
        return condensed
    except Exception as e:
        # On any failure, fall back to the raw question — retrieval will just
        # be slightly less precise.
        logger.warning(f"[CONDENSE] failed ({e}); using raw question")
        return question


SYSTEM_INSTRUCTION = (
    "You are a precise document assistant. Answer the user's question using ONLY "
    "the numbered context blocks provided. After every sentence that uses a fact "
    "from a block, append its citation in square brackets like [1] or [2,5]. "
    "If the answer is not present in the context, reply exactly: "
    '"I could not find that in the document." '
    "Do not invent citations. Do not reference your own knowledge. "
    "Write clearly and concisely."
)


def _build_context_block(retrieved: list[dict]) -> str:
    parts = []
    for i, r in enumerate(retrieved, start=1):
        snippet = r["text"].strip().replace("\n\n", "\n")
        parts.append(f"[{i}] (page {r['page']})\n{snippet}")
    return "\n\n".join(parts)


def _history_to_contents(history: list[dict]) -> list[types.Content]:
    """Map our {role: user/assistant, content: str} history to genai Contents."""
    contents: list[types.Content] = []
    for msg in history[-6:]:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(
            types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])])
        )
    return contents


def generate_grounded_answer(
    question: str,
    retrieved: list[dict],
    history: list[dict] | None = None,
) -> str:
    """
    Call Gemini with the retrieved context + last few turns of chat history.

    `retrieved` is the list returned by vector_store.match_chunks.
    `history` is [{role, content}, …] — only the last six turns are sent.
    """
    history = history or []
    client = _get_client()

    contents = _history_to_contents(history)
    context_block = _build_context_block(retrieved)
    final_user_msg = (
        f"Context blocks from the document:\n\n{context_block}\n\n"
        f"Question: {question}"
    )
    contents.append(
        types.Content(role="user", parts=[types.Part.from_text(text=final_user_msg)])
    )

    resp = _with_retry(
        lambda: client.models.generate_content(
            model=CHAT_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.1,
                max_output_tokens=1024,
            ),
        ),
        op="generate_grounded_answer",
    )
    return (resp.text or "").strip()
