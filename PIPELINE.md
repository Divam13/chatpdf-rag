# ChatPDF End-to-End Pipeline Specification & Reference Guide

This document provides a comprehensive, phase-by-phase technical breakdown of the entire pipeline powering **ChatPDF**. It specifies every tool, library, model, prompt, data structure, schema, threshold, and edge-case fallback mechanism employed across the three core operational pipelines:

1. [Document Ingestion Pipeline](#1-document-ingestion-pipeline) (Upload & Parsing $\rightarrow$ BBox Extraction $\rightarrow$ Chunking $\rightarrow$ Embedding $\rightarrow$ Persistence)
2. [Conversational RAG & Retrieval Pipeline](#2-conversational-rag--retrieval-pipeline) (Message Intake $\rightarrow$ Question Condensation $\rightarrow$ Query Embedding $\rightarrow$ pgvector Search $\rightarrow$ Grounded Answer Generation $\rightarrow$ Citation Extraction)
3. [Client Interaction & Spatial Highlighting Pipeline](#3-client-interaction--spatial-highlighting-pipeline) (Citation Badging $\rightarrow$ Page Synchronisation $\rightarrow$ Coordinate Scaling $\rightarrow$ BBox Pulse Overlay)

---

## Architecture Matrix: Phase-by-Phase Component Inventory

| Phase | Sub-Step / Component | Technology / Library | Model / Protocol / Algorithm | Primary File & Function | Inputs | Outputs |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Ingestion** | 1.1 Ingestion Intake & Auth | FastAPI, `python-jose`, Pydantic | JWT (HS256) + multipart/form-data | `backend/routes/pdfs.py`<br/>`upload_pdf()` | `UploadFile`, Bearer Token | Temp file path on disk, `user_id`, `pdf_id` |
| **Ingestion** | 1.2 Binary Storage | Supabase Storage (`supabase-py`) | HTTP REST Upload | `backend/routes/pdfs.py`<br/>`upload_pdf()` | Raw PDF bytes | `supabase_url`, `storage_path` |
| **Ingestion** | 1.3 Text & Bounding Box Extraction | PyMuPDF (`fitz`) | `doc.get_text("blocks")` | `backend/ingest.py`<br/>`extract_spans()` | Disk PDF file | `list[TextSpan]` (text, bbox, page dimensions) |
| **Ingestion** | 1.4 Text Cleaning & Normalization | Python RegEx (`re`) | Hyphenation joining & whitespace compaction | `backend/ingest.py`<br/>`_clean()` | Raw block text | Normalized continuous text |
| **Ingestion** | 1.5 Page-Isolated Spatial Chunking | Custom Python Chunking Engine | Page-isolated sliding accumulator | `backend/ingest.py`<br/>`chunk_spans()` | `list[TextSpan]` | `list[Chunk]` with merged `_union_bbox` |
| **Ingestion** | 1.6 Document Embedding | Google GenAI SDK (`google-genai`) | `gemini-embedding-001` (768-d, Matryoshka) | `backend/gemini_client.py`<br/>`embed_documents()` | Batch of chunk texts (`BATCH=8`) | 768-d L2-normalized float vectors |
| **Ingestion** | 1.7 Vector & Metadata Storage | Supabase Postgres + `pgvector` | PostgREST batch INSERT (Batch 200) | `backend/vector_store.py`<br/>`insert_chunks()` | Vector rows + spatial metadata | Rows written to `public.chunks` table |
| **Ingestion** | 1.8 Catalog Persistence | MongoDB Atlas + `motor` | Async MongoDB driver | `backend/routes/pdfs.py`<br/>`upload_pdf()` | PDF document metadata | MongoDB `ObjectId`, HTTP 201 `PDFOut` |
| **RAG** | 2.1 Message Intake & State Verification | FastAPI, `motor` | REST `POST /api/chats/{id}/message` | `backend/routes/chats.py`<br/>`send_message()` | `chat_id`, user message, JWT | Chat history, active `pdf_id` |
| **RAG** | 2.2 Question Condensation | Google GenAI SDK (`google-genai`) | `gemini-2.5-flash` (`temperature=0.0`) | `backend/gemini_client.py`<br/>`condense_question()` | Current question + last 4 history turns | Standalone de-referenced query string |
| **RAG** | 2.3 Query Vectorization | Google GenAI SDK (`google-genai`) | `gemini-embedding-001` (`RETRIEVAL_QUERY`) | `backend/gemini_client.py`<br/>`embed_query()` | Standalone query string | 768-d L2-normalized query vector |
| **RAG** | 2.4 Vector Similarity Retrieval | Supabase pgvector + PostgreSQL | Cosine distance (`<=>`) via IVFFlat index | `backend/vector_store.py`<br/>`match_chunks()` | Query vector, `user_id`, `pdf_id`, `top_k=5` | Top-5 ranked chunks with similarity scores |
| **RAG** | 2.5 Grounded Context Formulation | Python String Template | Indexed Markdown Blocks `[1]`, `[2]`, ... | `backend/gemini_client.py`<br/>`_build_context_block()` | Top-k chunks | Formatted context string + user question |
| **RAG** | 2.6 LLM Response Generation | Google GenAI SDK (`google-genai`) | `gemini-2.5-flash` (`temperature=0.1`) | `backend/gemini_client.py`<br/>`generate_grounded_answer()` | Formatted prompt + last 6 chat history turns | Grounded response text with bracketed citations |
| **RAG** | 2.7 Citation Parsing & Refusal Guard | Python RegEx + Logic Validator | Regex pattern `\[(\d+(?:\s*,\s*\d+)*)\]` | `backend/chat_engine.py`<br/>`answer_question()` | Raw LLM output | Sanitized answer + structured `Citation` objects |
| **RAG** | 2.8 Chat History Update | MongoDB Atlas + `motor` | Atomic `$push` update | `backend/routes/chats.py`<br/>`send_message()` | User message & Assistant message | Updated `ChatOut` response payload |
| **Frontend** | 3.1 Citation Badge Render | React 19 / Next.js 16 | Reactive DOM button components | `frontend/src/app/chat/[id]/page.js` | `citations` list in message | Clickable badges: `[p<page>#<chunk>]` |
| **Frontend** | 3.2 Viewport Navigation & BBox Scaling | `react-pdf` (`pdfjs-dist@5.4.296`) + CSS | Viewport coordinate ratio mapping | `frontend/src/components/PdfViewer.js` | BBox `[x0, y0, x1, y1]`, page dims | Highlight rect rendered & page in view |

---

## 1. Document Ingestion Pipeline

The ingestion pipeline converts arbitrary unstructured PDF documents into clean, isolated text chunks annotated with precise 2D spatial coordinates and indexed in high-dimensional vector space.

```mermaid
flowchart TD
    A[Client: POST /api/pdfs/upload] --> B[FastAPI Endpoint: Auth & Extension Check]
    B --> C[Buffer File to Temporary Disk Directory]
    C --> D[Supabase Storage: Upload Binary PDF]
    C --> E[PyMuPDF / fitz: Extract Blocks with BBoxes]
    E --> F{Any Text Extracted?}
    F -- No --> F1[Raise 400: Scanned/Image-only PDF]
    F -- Yes --> G[Text Normalization & Hyphenation Repair]
    G --> H[Page-Isolated Chunking Engine]
    H --> I[Compute Union Bounding Box per Chunk]
    I --> J[Micro-Batch Embedding: gemini-embedding-001]
    J --> K[Matryoshka L2 Vector Normalization]
    K --> L[Supabase pgvector: Batch Insert into chunks table]
    L --> M[MongoDB: Record PDF Metadata doc]
    M --> N[Return HTTP 201 PDFOut Response]
```

### Phase 1.1: File Reception, Authentication & Buffering
- **Endpoint**: `POST /api/pdfs/upload`
- **File**: [`backend/routes/pdfs.py`](file:///c:/Users/admin/Desktop/new1/chatpdf-rag/backend/routes/pdfs.py#L31-L60)
- **Authentication**: JWT Bearer token resolved via `get_current_user` (`auth.py`). Extracts user ID (`user_id`).
- **Validation**: Checks `file.filename.lower().endswith(".pdf")`. If invalid, immediately raises `HTTPException(status_code=400, detail="Only PDF files are accepted")`.
- **Identity Assignment**: Generates a cryptographically random BSON `ObjectId` for `pdf_id`.
- **Disk Buffering**:
  ```python
  tmp_dir = tempfile.mkdtemp()
  tmp_path = os.path.join(tmp_dir, file.filename)
  content = await file.read()
  with open(tmp_path, "wb") as f:
      f.write(content)
  ```
  *Design Rationale*: Writing to an ephemeral disk directory allows PyMuPDF to seek through file descriptors with maximum C-level memory efficiency rather than keeping multi-megabyte buffers entirely in Python memory.

### Phase 1.2: Raw File Persistence (Blob Storage)
- **Target**: Supabase Storage Bucket (`os.getenv("SUPABASE_BUCKET", "pdfs")`)
- **Storage Path Schema**: `{user_id}/{pdf_id}/{file.filename}`
- **SDK Call**:
  ```python
  supabase.storage.from_(bucket).upload(
      path=storage_path,
      file=content,
      file_options={"content-type": "application/pdf"}
  )
  ```
- **Public URL**: Formatted as `{SUPABASE_URL}/storage/v1/object/public/{bucket}/{storage_path}`.

### Phase 1.3: Text & Bounding Box Extraction
- **Module**: [`backend/ingest.py`](file:///c:/Users/admin/Desktop/new1/chatpdf-rag/backend/ingest.py#L73-L107)
- **Engine**: PyMuPDF (`fitz.open(pdf_path)`)
- **Block Iteration**: For each page `page_idx` (1-indexed):
  - Extracts page dimensions: `page_rect.width`, `page_rect.height` in PDF points ($1\text{ pt} = \frac{1}{72}\text{ inch}$).
  - Invokes `page.get_text("blocks")` returning tuples `(x0, y0, x1, y1, block_text, block_no, block_type)`.
  - **Block Filtering**: Evaluates `btype == 0` (plain text blocks only; skips `btype == 1` raster/vector image blocks).
- **Data Model (`TextSpan`)**:
  ```python
  @dataclass
  class TextSpan:
      page: int          # 1-indexed page number
      text: str          # Normalized text string
      x0: float          # Left coordinate (PDF points)
      y0: float          # Top coordinate (PDF points, origin top-left)
      x1: float          # Right coordinate (PDF points)
      y1: float          # Bottom coordinate (PDF points)
      page_width: float  # Absolute page width in points
      page_height: float # Absolute page height in points
  ```

### Phase 1.4: Text Cleaning & Normalization
- **Function**: `_clean(text: str)` in [`backend/ingest.py`](file:///c:/Users/admin/Desktop/new1/chatpdf-rag/backend/ingest.py#L63-L71)
- **Normalization Rules**:
  1. Soft Hyphen Removal: `text.replace("\xad", "")`
  2. Carriage Return Strip: `text.replace("\r", "")`
  3. Hyphenated Line-Break Stitching: `re.sub(r"-\n(?=\w)", "", text)` ensures words split across margins (e.g., `optimi-\nzation`) are merged cleanly (`optimization`).
  4. Paragraph-Preserving Whitespace Collapsing: Converts single newlines `(?<!\n)\n(?!\n)` to spaces while preserving true double newlines (`\n\n`) for paragraph structures.
  5. Whitespace Compacting: `re.sub(r"[ \t]+", " ", text).strip()`

### Phase 1.5: Page-Isolated Spatial Chunking Engine
- **Function**: `chunk_spans(spans: list[TextSpan])` in [`backend/ingest.py`](file:///c:/Users/admin/Desktop/new1/chatpdf-rag/backend/ingest.py#L119-L171)
- **Tuning Parameters**:
  - `CHUNK_TARGET_CHARS = 1600` ($\approx 400$ tokens, fits well within embedding context limit).
  - `CHUNK_OVERLAP_CHARS = 200` (preserves contextual continuity across chunk boundaries).
  - `MIN_CHUNK_CHARS = 120` (discards isolated headers, page numbers, or noise).
- **Invariant Rules**:
  1. **Strict Page Boundary Isolation**: Chunks **never** span multiple pages. If content overflows onto page $N+1$, the buffer is flushed and a new chunk begins on page $N+1$.
     *Rationale*: Preserves a 1-to-1 mapping between a chunk and a single page bounding box.
  2. **Geometric Reading Order**: Spans on each page are sorted top-to-bottom, then left-to-right:
     `page_spans.sort(key=lambda s: (round(s.y0, 1), s.x0))`
  3. **Union Bounding Box Aggregation**:
     $$\text{bbox} = [\min(x_0), \min(y_0), \max(x_1), \max(y_1)]$$
- **Data Model (`Chunk`)**:
  ```python
  @dataclass
  class Chunk:
      chunk_index: int       # Sequential index per PDF
      page: int              # 1-indexed page
      text: str              # Merged text
      page_width: float      # Page width
      page_height: float     # Page height
      bbox: list[float]      # [x0, y0, x1, y1] bounding box
  ```

### Phase 1.6: Embedding Generation & Resiliency
- **Function**: `embed_documents(texts: Iterable[str])` in [`backend/gemini_client.py`](file:///c:/Users/admin/Desktop/new1/chatpdf-rag/backend/gemini_client.py#L110-L141)
- **Model**: `gemini-embedding-001` via `google-genai` SDK
- **Task Type**: `task_type="RETRIEVAL_DOCUMENT"`
- **Dimensionality (Matryoshka)**: `output_dimensionality=768` (downsampled from 3072 dimensions to match pgvector storage specs).
- **Batching**: Grouped into micro-batches of `BATCH = 8` texts per call to prevent free-tier Token-Per-Minute (TPM) quota starvation.
- **Resiliency & Exponential Backoff** (`_with_retry`):
  - Retries up to 5 attempts on HTTP 429 (`RESOURCE_EXHAUSTED`) and 5xx server errors.
  - Inspects error message for Gemini's recommended cooldown: `retry in (\d+(?:\.\d+)?)s`.
  - Sleep duration: $\min(\text{hint}, 30\text{s})$ or $\min(2^{\text{attempt}} + \text{jitter}, 30\text{s})$.
- **L2 Vector Normalization**:
  $$v_{\text{norm}} = \frac{v}{\|v\|_2} = \frac{v}{\sqrt{\sum_{i=1}^{d} v_i^2}}$$
  *Rationale*: Matryoshka sub-vector truncations must be L2-normalized so that inner product equals cosine similarity.

### Phase 1.7: Vector Store Persistence (pgvector)
- **Module**: [`backend/vector_store.py`](file:///c:/Users/admin/Desktop/new1/chatpdf-rag/backend/vector_store.py#L26-L55)
- **Database**: Supabase PostgreSQL with `vector` extension
- **Table Definition**:
  ```sql
  create table public.chunks (
      id              uuid primary key default gen_random_uuid(),
      user_id         text not null,
      pdf_id          text not null,
      chunk_index     int  not null,
      page            int  not null,
      page_width      double precision not null,
      page_height     double precision not null,
      bbox            jsonb not null,
      text            text not null,
      embedding       vector(768) not null,
      created_at      timestamptz not null default now()
  );
  create index chunks_user_pdf_idx on public.chunks (user_id, pdf_id);
  create index chunks_embedding_idx on public.chunks using ivfflat (embedding vector_cosine_ops) with (lists = 100);
  ```
- **Batching**: Payload sent in chunks of 200 rows via PostgREST to adhere to request payload limits.

### Phase 1.8: Catalog Registration
- **Database**: MongoDB Atlas (`database.pdfs_col()`)
- **Document Payload**:
  ```json
  {
    "_id": ObjectId("..."),
    "user_id": "<user_id>",
    "filename": "annual_report.pdf",
    "supabase_url": "https://.../annual_report.pdf",
    "storage_path": "<user_id>/<pdf_id>/annual_report.pdf",
    "page_count": 24,
    "chunk_count": 52,
    "created_at": "2026-10-09T08:00:00Z"
  }
  ```

---

## 2. Conversational RAG & Retrieval Pipeline

The RAG pipeline resolves user follow-ups, retrieves semantically relevant text chunks from pgvector, and uses Gemini 2.5 Flash to generate grounded responses with verifiable citations.

```mermaid
sequenceDiagram
    autonumber
    actor User as User
    participant FE as Next.js Client
    participant API as FastAPI (/api/chats/{id}/message)
    participant Mongo as MongoDB Atlas
    participant Condenser as Gemini 2.5 Flash (Condense)
    participant Embedder as Gemini Embeddings (001)
    participant PGV as Supabase pgvector (match_chunks)
    participant LLM as Gemini 2.5 Flash (Grounded Chat)

    User->>FE: Types query: "Break that down by passenger & cargo"
    FE->>API: POST /api/chats/{id}/message
    API->>Mongo: Fetch Chat History & PDF Metadata
    API->>Condenser: condense_question(q, history[-4:])
    Condenser-->>API: Standalone: "Break down airport performance in H1-26..."
    API->>Embedder: embed_query(standalone_query, task_type=RETRIEVAL_QUERY)
    Embedder-->>API: 768-d L2-normalized vector
    API->>PGV: RPC match_chunks(vector, user_id, pdf_id, top_k=5)
    PGV-->>API: Top 5 Chunks (Text, Page, BBox, Similarity)
    API->>LLM: generate_grounded_answer(original_q, chunks[1..5], history[-6:])
    LLM-->>API: "Passenger traffic rose [1], cargo reached [2]."
    API->>API: Regex extract [1], [2] -> Build Citation objects
    API->>Mongo: $push user & assistant messages
    API-->>FE: Return ChatOut with citations
    FE-->>User: Displays message with interactive source badges
```

### Phase 2.1: Intake & Context Retrieval
- **Endpoint**: `POST /api/chats/{chat_id}/message`
- **File**: [`backend/routes/chats.py`](file:///c:/Users/admin/Desktop/new1/chatpdf-rag/backend/routes/chats.py#L146-L188)
- **Validation**: Verifies `chat_id` belongs to `current_user["_id"]`, loads existing message history, and checks `pdf_id`.
- **History Slicing**: Converts chat history to `[{"role": m["role"], "content": m["content"]}]`.

### Phase 2.2: Conversational Question Condensation
- **Function**: `condense_question(question, history)` in [`backend/gemini_client.py`](file:///c:/Users/admin/Desktop/new1/chatpdf-rag/backend/gemini_client.py#L182-L235)
- **Model**: `gemini-2.5-flash` (`temperature=0.0`, `max_output_tokens=512`)
- **System Instruction**:
  > *"You rewrite a follow-up question into a standalone question that can be understood without the prior conversation. Resolve any pronoun or demonstrative reference ('it', 'that', 'this', 'those', 'those changes') using the conversation. Preserve every concrete noun and qualifier from the follow-up. If the follow-up is already self-contained, return it unchanged. Output exactly one line containing only the rewritten question."*
- **Few-Shot Examples**:
  - *User*: "Summarize airport performance in H1-26." $\rightarrow$ *Assistant*: "Passenger traffic rose to 49.3M..."
  - *Follow-up*: "Break that down into passenger and cargo changes."
  - *Standalone*: "Break down airport performance in H1-26 into passenger and cargo changes."
- **Window Size**: Slices only the last 4 messages (`history[-4:]`) to limit token consumption while resolving references.
- **Fail-Safe Mechanism**: If condensation encounters any API error or rate limit, it falls back to using the raw question text.

### Phase 2.3: Query Embedding
- **Function**: `embed_query(text: str)` in [`backend/gemini_client.py`](file:///c:/Users/admin/Desktop/new1/chatpdf-rag/backend/gemini_client.py#L143-L158)
- **Model**: `gemini-embedding-001`
- **Task Type**: `task_type="RETRIEVAL_QUERY"`
  *Design Note*: Asymmetric retrieval requires query vectors to use `RETRIEVAL_QUERY` while stored documents use `RETRIEVAL_DOCUMENT`. This trains the embedding projection to align questions with candidate answers.
- **Dimensionality**: 768 float dimensions, L2-normalized via `_l2_normalize()`.

### Phase 2.4: Vector Cosine Similarity Search
- **Function**: `match_chunks()` in [`backend/vector_store.py`](file:///c:/Users/admin/Desktop/new1/chatpdf-rag/backend/vector_store.py#L57-L77)
- **Database Function**: `public.match_chunks` PostgreSQL RPC
- **SQL Implementation**:
  ```sql
  select
      c.id, c.chunk_index, c.page, c.page_width, c.page_height,
      c.bbox, c.text,
      1 - (c.embedding <=> query_embedding) as similarity
  from public.chunks c
  where c.user_id = p_user_id
    and c.pdf_id  = p_pdf_id
  order by c.embedding <=> query_embedding
  limit match_count;
  ```
- **Operator**: `<=>` represents cosine distance in `pgvector`.
- **Top-K**: Default `top_k = 5`.
- **Tenant Isolation**: Explicitly scoped by `p_user_id` and `p_pdf_id`.
- **Early Exit**: If `match_chunks` returns 0 rows, the engine returns `"I could not find that in the document."` with `citations: []` without invoking the LLM.

### Phase 2.5 & 2.6: Grounded Prompt Assembly & LLM Generation
- **Function**: `generate_grounded_answer(question, retrieved, history)` in [`backend/gemini_client.py`](file:///c:/Users/admin/Desktop/new1/chatpdf-rag/backend/gemini_client.py#L268-L304)
- **Model**: `gemini-2.5-flash` (`temperature=0.1`, `max_output_tokens=1024`)
- **System Instruction**:
  > *"You are a precise document assistant. Answer the user's question using ONLY the numbered context blocks provided. After every sentence that uses a fact from a block, append its citation in square brackets like [1] or [2,5]. If the answer is not present in the context, reply exactly: 'I could not find that in the document.' Do not invent citations. Do not reference your own knowledge. Write clearly and concisely."*
- **Context Block Format**:
  ```text
  [1] (page 3)
  Passenger traffic during the first half reached 49.3 million...

  [2] (page 4)
  Cargo throughput expanded by 12.4% year-over-year...
  ```
- **Chat History Integration**: Last 6 messages (`history[-6:]`) passed as conversation turns (`role="user"` / `role="model"`).

### Phase 2.7: Citation Extraction & Refusal Guard
- **File**: [`backend/chat_engine.py`](file:///c:/Users/admin/Desktop/new1/chatpdf-rag/backend/chat_engine.py#L20-L120)
- **Refusal Detection**:
  ```python
  REFUSAL = "I could not find that in the document."
  if REFUSAL in answer:
      return {"answer": REFUSAL, "citations": []}
  ```
  *Design Rule*: If the model refuses to answer because information is missing, all citations are suppressed to avoid linking unrelated sources.
- **Citation Parsing**:
  - Regular Expression: `_CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")`
  - Validates parsed indices: $1 \le \text{idx} \le \text{len(retrieved)}$.
- **Safety Fallback**: If the model answers without explicit `[n]` bracket notations, the engine defaults to `used = [1]` so the user always receives a verifiable source badge.
- **Citation Payload Output**:
  ```json
  {
    "label": "p3#12",
    "page": 3,
    "bbox": [54.0, 120.5, 558.0, 240.8],
    "page_width": 612.0,
    "page_height": 792.0,
    "snippet": "Passenger traffic during the first half reached 49.3 million..."
  }
  ```

### Phase 2.8: Persistence & Title Auto-Generation
- **Database**: MongoDB Atlas (`chats_col()`)
- **First-Message Title Logic**: If the chat previously had no messages, the title is automatically generated from the first 50 characters of the prompt:
  ```python
  new_title = body.content[:50] + ("…" if len(body.content) > 50 else "")
  ```
- **Atomic Mutation**: `$push` adds both user message and assistant message with citation metadata in a single transaction.

---

## 3. Client Interaction & Spatial Highlighting Pipeline

The frontend connects citation data from the backend to the visual PDF document, allowing users to jump directly to cited source text.

```mermaid
flowchart LR
    A[User clicks Citation Badge e.g. 'p3#12'] --> B[Update Active Highlight State in React]
    B --> C[PdfViewer navigates to Page 3]
    C --> D[Retrieve Page Viewport Dimensions]
    D --> E[Compute Normalized CSS Coordinates]
    E --> F[Render Pulsing Translucent Overlay on PDF Canvas]
```

### Phase 3.1: Interactive Citation Badges
- **Files**: `frontend/src/app/chat/[id]/page.js`, `frontend/src/components/ChatMessage.js`
- **Citation Render**: Assistant message text displays interactive badges:
  ```jsx
  <button
    key={idx}
    className="citation-badge"
    onClick={() => onSelectCitation(citation)}
  >
    {citation.label}
  </button>
  ```

### Phase 3.2: Coordinate Translation & Visual Overlay
- **File**: `frontend/src/components/PdfViewer.js`
- **PDF Engine**: `react-pdf` (pinned to `pdfjs-dist@5.4.296`)
- **Coordinate Translation**:
  PDF points have an origin at the **top-left** (in PyMuPDF extraction) where $y$ increases downwards. The frontend scales these points to viewport percentages:
  $$\text{left} = \frac{x_0}{\text{page\_width}} \times 100\%$$
  $$\text{top} = \frac{y_0}{\text{page\_height}} \times 100\%$$
  $$\text{width} = \frac{x_1 - x_0}{\text{page\_width}} \times 100\%$$
  $$\text{height} = \frac{y_1 - y_0}{\text{page\_height}} \times 100\%$$
- **Visual Pulse Styling**:
  An overlay `div` is placed over the PDF page canvas with CSS animations:
  ```css
  .pdf-highlight-overlay {
    position: absolute;
    background-color: rgba(99, 102, 241, 0.35);
    border: 2px solid #6366f1;
    border-radius: 4px;
    pointer-events: none;
    animation: pulseHighlight 2s ease-in-out infinite;
  }
  ```

---

## 4. Error Handling & Failure Matrix

| Failure Mode | Pipeline Phase | Detection Point | Handling & Recovery Strategy |
| :--- | :--- | :--- | :--- |
| **Non-PDF file upload** | Ingestion 1.1 | `routes/pdfs.py` | Immediate `400 Bad Request` ("Only PDF files are accepted"). |
| **Scanned / Image-Only PDF** | Ingestion 1.3 | `ingest.py:extract_spans` | Detects `len(spans) == 0`. Raises `ValueError` ("No extractable text found..."), returned as `400 Bad Request`. |
| **Empty or Tiny Text** | Ingestion 1.5 | `ingest.py:chunk_spans` | Spans below `MIN_CHUNK_CHARS` (120 chars) are discarded. Raises `ValueError` if zero chunks are generated. |
| **Gemini 429 Rate Limit (RPM/TPM)** | Ingestion 1.6 & RAG 2.2-2.6 | `gemini_client.py:_with_retry` | Catches `genai_errors.ClientError(code=429)`. Extracts `retry in Ns` server hint; applies exponential backoff with jitter up to 5 attempts. |
| **Gemini 5xx Server Outage** | Ingestion 1.6 & RAG 2.2-2.6 | `gemini_client.py:_with_retry` | Catches `genai_errors.ServerError`. Exponential backoff up to 5 attempts before raising. |
| **Missing Info / Out of Scope Question** | RAG 2.6 | `chat_engine.py` | Model outputs exact string `"I could not find that in the document."`. Citation extraction suppresses all citations to avoid hallucinated references. |
| **Question Condensation Failure** | RAG 2.2 | `gemini_client.py:condense_question` | Logs warning; falls back to the original raw question string. |
| **Omitted Citation Markers in Answer** | RAG 2.7 | `chat_engine.py:answer_question` | If model produces an answer without `[n]` bracket notations, falls back to Chunk #1 (`used = [1]`). |

---

## 5. Environment Variables & System Configuration

```bash
# === Gemini API ===
GEMINI_API_KEY="AIzaSy..."
GEMINI_EMBED_MODEL="gemini-embedding-001"
GEMINI_CHAT_MODEL="gemini-2.5-flash"

# === Supabase (Storage & pgvector) ===
SUPABASE_URL="https://xyz.supabase.co"
SUPABASE_SERVICE_KEY="eyJhbG..."
SUPABASE_BUCKET="pdfs"

# === MongoDB Atlas (App Metadata & Chat History) ===
MONGODB_URI="mongodb+srv://user:pass@cluster.mongodb.net/chatpdf?retryWrites=true&w=majority"
MONGODB_DB_NAME="chatpdf"

# === Security & Authentication ===
JWT_SECRET="super-secret-random-hex-key"
JWT_ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES="43200" # 30 days
```
