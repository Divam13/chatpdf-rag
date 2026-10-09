-- ChatPDF schema: pgvector-backed chunk store + RPC.
-- Run this once in the Supabase SQL editor (or via `psql`) after provisioning the project.

create extension if not exists vector;
create extension if not exists "pgcrypto";

-- One row per retrieval chunk. Embeddings are 768-dim (Gemini text-embedding-004).
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
    embedding       vector(768) not null,
    created_at      timestamptz not null default now()
);

create index if not exists chunks_user_pdf_idx
    on public.chunks (user_id, pdf_id);

-- IVFFlat for fast ANN search. 100 lists is a sensible default for tens of
-- thousands of vectors; bump it if your corpus grows past ~1M chunks.
create index if not exists chunks_embedding_idx
    on public.chunks
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

-- Vector search scoped to a single user's single PDF.
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
