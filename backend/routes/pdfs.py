"""
PDF upload, list, view, and delete routes.

Uploads go to Supabase Storage; chunks (text + embeddings + bboxes) go into
the `chunks` pgvector table via the ingest pipeline.
"""

import asyncio
import logging
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from auth import decode_access_token, get_current_user
from database import chats_col, get_supabase, get_supabase_bucket, pdfs_col
from ingest import ingest_pdf
from models import PDFOut
from vector_store import delete_pdf_chunks

logger = logging.getLogger("chatpdf.pdfs")

router = APIRouter(prefix="/api/pdfs", tags=["pdfs"])


@router.post("/upload", response_model=PDFOut, status_code=201)
async def upload_pdf(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    total_start = time.time()

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    user_id = current_user["_id"]
    pdf_id = str(ObjectId())

    logger.info(
        f"[UPLOAD] ▶ START user={user_id}, pdf_id={pdf_id}, filename={file.filename}"
    )

    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, file.filename)
    try:
        # 1. Buffer to disk
        t0 = time.time()
        content = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(content)
        size_mb = len(content) / (1024 * 1024)
        logger.info(f"[UPLOAD] Step 1 — buffered {size_mb:.1f} MB in {time.time()-t0:.3f}s")

        # 2. Push to Supabase storage
        t0 = time.time()
        bucket = get_supabase_bucket()
        storage_path = f"{user_id}/{pdf_id}/{file.filename}"
        supabase = get_supabase()
        try:
            supabase.storage.from_(bucket).upload(
                path=storage_path,
                file=content,
                file_options={"content-type": "application/pdf"},
            )
        except Exception as e:
            logger.exception(f"[UPLOAD] Supabase upload failed: {e}")
            raise HTTPException(status_code=500, detail=f"Supabase upload failed: {e}")
        logger.info(f"[UPLOAD] Step 2 — Supabase upload done in {time.time()-t0:.3f}s")

        supabase_url = (
            f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/{bucket}/{storage_path}"
        )

        # 3. Ingest: parse, chunk, embed, store chunks in pgvector
        t0 = time.time()
        try:
            result = await asyncio.to_thread(ingest_pdf, tmp_path, user_id, pdf_id)
        except ValueError as e:
            # Friendly error for scanned/empty PDFs.
            logger.warning(f"[UPLOAD] Ingest rejected PDF: {e}")
            raise HTTPException(
                status_code=400, 
                detail="This PDF has no extractable text (it may be scanned). Text-based PDFs only for now."
            )
        except Exception as e:
            logger.exception(f"[UPLOAD] Ingest failed: {e}")
            raise HTTPException(status_code=500, detail=f"PDF ingest failed: {e}")
        logger.info(f"[UPLOAD] Step 3 — ingest done in {time.time()-t0:.2f}s ({result})")

        # 4. Save metadata
        t0 = time.time()
        pdf_doc = {
            "_id": ObjectId(pdf_id),
            "user_id": user_id,
            "filename": file.filename,
            "supabase_url": supabase_url,
            "storage_path": storage_path,
            "page_count": result["page_count"],
            "chunk_count": result["chunk_count"],
            "uploaded_at": datetime.now(timezone.utc),
        }
        await pdfs_col().insert_one(pdf_doc)
        logger.info(f"[UPLOAD] Step 4 — Mongo insert in {time.time()-t0:.3f}s")

        total = time.time() - total_start
        logger.info(f"[UPLOAD] ✅ DONE pdf_id={pdf_id} in {total:.2f}s")
        return PDFOut(
            id=pdf_id,
            filename=file.filename,
            supabase_url=supabase_url,
            page_count=result["page_count"],
            uploaded_at=pdf_doc["uploaded_at"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[UPLOAD] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.get("/", response_model=list[PDFOut])
async def list_pdfs(current_user: dict = Depends(get_current_user)):
    user_id = current_user["_id"]
    cursor = pdfs_col().find({"user_id": user_id}).sort("uploaded_at", -1)
    results = []
    async for doc in cursor:
        results.append(
            PDFOut(
                id=str(doc["_id"]),
                filename=doc["filename"],
                supabase_url=doc["supabase_url"],
                page_count=doc.get("page_count", 0),
                uploaded_at=doc["uploaded_at"],
            )
        )
    return results


@router.delete("/{pdf_id}", status_code=204)
async def delete_pdf(pdf_id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user["_id"]
    logger.info(f"[DELETE_PDF] pdf_id={pdf_id}, user={user_id}")
    pdf_doc = await pdfs_col().find_one({"_id": ObjectId(pdf_id), "user_id": user_id})
    if not pdf_doc:
        raise HTTPException(status_code=404, detail="PDF not found")

    # Best-effort: remove from Supabase storage.
    try:
        bucket = get_supabase_bucket()
        get_supabase().storage.from_(bucket).remove([pdf_doc["storage_path"]])
    except Exception as e:
        logger.warning(f"[DELETE_PDF] Supabase storage delete failed (best effort): {e}")

    # Remove pgvector rows.
    try:
        await asyncio.to_thread(delete_pdf_chunks, user_id, pdf_id)
    except Exception as e:
        logger.warning(f"[DELETE_PDF] pgvector chunk delete failed (best effort): {e}")

    chat_result = await chats_col().delete_many({"pdf_id": pdf_id, "user_id": user_id})
    logger.info(f"[DELETE_PDF] removed {chat_result.deleted_count} chats")

    await pdfs_col().delete_one({"_id": ObjectId(pdf_id)})
    logger.info(f"[DELETE_PDF] ✅ done pdf_id={pdf_id}")


@router.get("/{pdf_id}/view")
async def view_pdf(pdf_id: str, token: str = ""):
    """
    Serve the PDF bytes for the in-app viewer. Accepts JWT via ?token=…
    because <iframe> / fetch from a worker can't easily send Authorization headers.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Token required")

    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    pdf_doc = await pdfs_col().find_one({"_id": ObjectId(pdf_id), "user_id": user_id})
    if not pdf_doc:
        raise HTTPException(status_code=404, detail="PDF not found")

    try:
        bucket = get_supabase_bucket()
        file_bytes = get_supabase().storage.from_(bucket).download(pdf_doc["storage_path"])
        return Response(
            content=file_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{pdf_doc["filename"]}"',
                # react-pdf fetches the PDF via XHR in the worker — the browser
                # treats this as cross-origin in production, so be explicit.
                "Cache-Control": "private, max-age=300",
            },
        )
    except Exception as e:
        logger.exception(f"[VIEW_PDF] download failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve PDF: {e}")
