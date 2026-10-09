"""
PDF ingestion pipeline (PyMuPDF + Gemini embeddings + Supabase pgvector).

Extracts text blocks with bounding boxes per page, groups them into
overlapping chunks sized for retrieval, embeds them with Gemini's
gemini-embedding-001 (768-d, L2-normalized), and writes them to
Supabase's `chunks` table.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Iterable

import fitz  # PyMuPDF
from dotenv import load_dotenv

from gemini_client import embed_documents
from vector_store import insert_chunks

load_dotenv()

logger = logging.getLogger("chatpdf.ingest")

# A chunk targets roughly this many characters; rule-of-thumb 4 chars ~= 1 token,
# so ~1.6k chars ≈ 400 tokens — comfortably under gemini-embedding-001's 2048 token cap.
CHUNK_TARGET_CHARS = 1600
CHUNK_OVERLAP_CHARS = 200
MIN_CHUNK_CHARS = 120  # drop tiny stray blocks


@dataclass
class TextSpan:
    """A continuous run of text on a page, with its bounding box (PDF points)."""
    page: int  # 1-indexed
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page_width: float
    page_height: float


@dataclass
class Chunk:
    """A retrieval chunk: text plus the union bbox of the spans that built it."""
    chunk_index: int
    page: int
    text: str
    page_width: float
    page_height: float
    bbox: list[float] = field(default_factory=list)  # [x0, y0, x1, y1]


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def _clean(text: str) -> str:
    text = text.replace("­", "").replace("\r", "")
    # Join hyphenated line breaks ("optimi-\nzation" -> "optimization").
    text = re.sub(r"-\n(?=\w)", "", text)
    # Convert single newlines to spaces, keep paragraph breaks.
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def extract_spans(pdf_path: str) -> list[TextSpan]:
    """Read a PDF and return a flat list of text spans with their bboxes."""
    t0 = time.time()
    spans: list[TextSpan] = []

    with fitz.open(pdf_path) as doc:
        for page_idx, page in enumerate(doc, start=1):
            page_rect = page.rect
            blocks = page.get_text("blocks")
            # blocks: list of (x0, y0, x1, y1, text, block_no, block_type)
            # block_type 0 = text, 1 = image — we keep text only.
            for x0, y0, x1, y1, block_text, _bno, btype in blocks:
                if btype != 0:
                    continue
                cleaned = _clean(block_text)
                if not cleaned:
                    continue
                spans.append(
                    TextSpan(
                        page=page_idx,
                        text=cleaned,
                        x0=float(x0),
                        y0=float(y0),
                        x1=float(x1),
                        y1=float(y1),
                        page_width=float(page_rect.width),
                        page_height=float(page_rect.height),
                    )
                )

    logger.info(
        f"[PARSE] PyMuPDF extracted {len(spans)} text blocks in {time.time()-t0:.2f}s"
    )
    return spans


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
def _union_bbox(spans: Iterable[TextSpan]) -> list[float]:
    xs0, ys0, xs1, ys1 = [], [], [], []
    for s in spans:
        xs0.append(s.x0); ys0.append(s.y0); xs1.append(s.x1); ys1.append(s.y1)
    return [min(xs0), min(ys0), max(xs1), max(ys1)]


def chunk_spans(spans: list[TextSpan]) -> list[Chunk]:
    """
    Group spans into chunks of ~CHUNK_TARGET_CHARS.

    Chunks never cross pages — this keeps the page/bbox single-valued per chunk
    so the frontend can highlight exactly one rectangle on one page.
    """
    chunks: list[Chunk] = []
    chunk_index = 0

    by_page: dict[int, list[TextSpan]] = {}
    for s in spans:
        by_page.setdefault(s.page, []).append(s)

    for page in sorted(by_page.keys()):
        page_spans = by_page[page]
        # Sort top-to-bottom, then left-to-right (fitz y grows downward).
        page_spans.sort(key=lambda s: (round(s.y0, 1), s.x0))

        buffer_spans: list[TextSpan] = []
        buffer_text = ""

        def flush():
            nonlocal buffer_spans, buffer_text, chunk_index
            text = buffer_text.strip()
            if len(text) >= MIN_CHUNK_CHARS and buffer_spans:
                chunk_index += 1
                chunks.append(
                    Chunk(
                        chunk_index=chunk_index,
                        page=page,
                        text=text,
                        page_width=buffer_spans[0].page_width,
                        page_height=buffer_spans[0].page_height,
                        bbox=_union_bbox(buffer_spans),
                    )
                )
            buffer_spans = []
            buffer_text = ""

        for span in page_spans:
            piece = span.text
            if buffer_text and len(buffer_text) + len(piece) + 2 > CHUNK_TARGET_CHARS:
                tail = buffer_text[-CHUNK_OVERLAP_CHARS:] if CHUNK_OVERLAP_CHARS else ""
                flush()
                buffer_text = tail
            buffer_spans.append(span)
            buffer_text = (buffer_text + "\n\n" + piece).strip() if buffer_text else piece

        flush()

    logger.info(f"[CHUNK] Built {len(chunks)} chunks across {len(by_page)} pages")
    return chunks


# ---------------------------------------------------------------------------
# Embed + persist
# ---------------------------------------------------------------------------
def ingest_pdf(pdf_path: str, user_id: str, pdf_id: str) -> dict:
    """
    Full pipeline: parse PDF → chunk → embed → store in Supabase pgvector.
    Returns {"page_count": int, "chunk_count": int}.
    """
    t_start = time.time()
    logger.info(f"[INGEST] ▶ user={user_id} pdf={pdf_id} path={pdf_path}")

    spans = extract_spans(pdf_path)
    if not spans:
        raise ValueError(
            "No extractable text found. This PDF may be scanned or image-only."
        )

    chunks = chunk_spans(spans)
    if not chunks:
        raise ValueError("PDF parsed but produced no chunks (text too short).")

    page_count = max(s.page for s in spans)

    t0 = time.time()
    logger.info(f"[INGEST] Embedding {len(chunks)} chunks via Gemini...")
    embeddings = embed_documents([c.text for c in chunks])
    logger.info(f"[INGEST] Embedded in {time.time()-t0:.2f}s")

    rows = []
    for chunk, vector in zip(chunks, embeddings):
        rows.append(
            {
                "user_id": user_id,
                "pdf_id": pdf_id,
                "chunk_index": chunk.chunk_index,
                "page": chunk.page,
                "page_width": chunk.page_width,
                "page_height": chunk.page_height,
                "bbox": chunk.bbox,
                "text": chunk.text,
                "embedding": vector,
            }
        )

    t0 = time.time()
    insert_chunks(rows)
    logger.info(f"[INGEST] Wrote {len(rows)} rows to Supabase in {time.time()-t0:.2f}s")

    total = time.time() - t_start
    logger.info(
        f"[INGEST] ✅ done — {page_count} pages / {len(chunks)} chunks in {total:.2f}s"
    )
    return {"page_count": page_count, "chunk_count": len(chunks)}


# ---------------------------------------------------------------------------
# CLI entry-point (smoke test)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    if len(sys.argv) < 2:
        print("Usage: python ingest.py <path_to_pdf> [user_id] [pdf_id]")
        sys.exit(1)

    pdf_file = sys.argv[1]
    user_id = sys.argv[2] if len(sys.argv) > 2 else "cli-user"
    pdf_id = sys.argv[3] if len(sys.argv) > 3 else "cli-pdf"

    if not os.path.exists(pdf_file):
        print(f"File not found: {pdf_file}")
        sys.exit(1)

    print(ingest_pdf(pdf_file, user_id=user_id, pdf_id=pdf_id))
