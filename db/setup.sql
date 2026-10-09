-- ==========================================================================
-- ChatPDF — Supabase / pgvector schema setup
-- ==========================================================================
--
-- Run this file once in the Supabase SQL Editor (or via psql) after creating
-- your Supabase project.
--
-- Prerequisites:
--   • A Supabase project with the "pgvector" extension available.
--
-- IMPORTANT: the embedding dimension (768) must match the value the backend
-- requests from Gemini via output_dimensionality. If you change EMBED_DIM
-- in gemini_client.py you must recreate this table with the new dimension.
-- ==========================================================================

-- 1. Enable required Postgres extensions
create extension if not exists vector;       -- pgvector for embedding storage & search
create extension if not exists "pgcrypto";   -- gen_random_uuid() for primary keys

-- 2. Chunk storage table
--    One row per retrieval chunk. Each chunk belongs to a single user's single
--    PDF and stores the text, its 768-d embedding, page number, bounding box
--    (in PDF points), and page dimensions so the frontend can scale the
--    highlight overlay.
create table if not exists public.chunks (
    id              uuid primary key default gen_random_uuid(),
    user_id         text not null,
    pdf_id          text not null,
    chunk_index     int  not null,
    page            int  not null,
    page_width      double precision not null,
    page_height     double precision not null,
    bbox            jsonb not null,           -- [x0, y0, x1, y1] in PDF points
    text            text not null,
    embedding       vector(768) not null,     -- gemini-embedding-001 Matryoshka @ 768-d
    created_at      timestamptz not null default now()
);

-- 3. Indexes
--    B-tree index for fast row filtering by tenant (user + PDF).
create index if not exists chunks_user_pdf_idx
    on public.chunks (user_id, pdf_id);

--    IVFFlat approximate nearest-neighbour index for cosine similarity search.
--    100 lists is reasonable for up to ~100k vectors. Increase if your corpus
--    grows past ~1M chunks.
create index if not exists chunks_embedding_idx
    on public.chunks
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

-- 4. Retrieval RPC
--    Called by the backend's vector_store.match_chunks() function.
--    Returns the top-N most similar chunks for a given user's PDF, ranked by
--    cosine similarity (1 − cosine_distance).
create or replace function public.match_chunks(
    query_embedding vector(768),
    p_user_id       text,
    p_pdf_id        text,
    match_count     int default 5
)
returns table (
    id           uuid,
    chunk_index  int,
    page         int,
    page_width   double precision,
    page_height  double precision,
    bbox         jsonb,
    text         text,
    similarity   double precision
)
language sql stable as $$
    select
        c.id,
        c.chunk_index,
        c.page,
        c.page_width,
        c.page_height,
        c.bbox,
        c.text,
        1 - (c.embedding <=> query_embedding) as similarity
    from public.chunks c
    where c.user_id = p_user_id
      and c.pdf_id  = p_pdf_id
    order by c.embedding <=> query_embedding
    limit match_count;
$$;
