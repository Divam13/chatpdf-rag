# Architecture

---

# 1. System Overview

ChatPDF follows a **distributed RAG-based system architecture** designed for:

- scalable semantic retrieval,
- precise source grounding,
- conversational querying,
- and cloud-native deployment.

The system converts uploaded PDFs into searchable semantic knowledge using:

- **PyMuPDF** for extraction,
- **Gemini Embeddings** for vectorization,
- **pgvector** for retrieval,
- and **Gemini 2.5 Flash** for grounded response generation.

---

# 2. High-Level System Design

```mermaid
flowchart TB

    USER[👤 User]

    subgraph Frontend
        FE[Next.js Frontend]
        VIEWER[PDF Viewer]
        CHAT[Chat Interface]
    end

    subgraph Backend
        API[FastAPI API Layer]
        INGEST[PDF Ingestion Engine]
        RETRIEVE[Retrieval Engine]
        GENERATE[LLM Generation Engine]
    end

    subgraph Storage
        MONGO[(MongoDB)]
        STORAGE[(Supabase Storage)]
        VECTOR[(pgvector)]
    end

    subgraph AI
        EMBED[Gemini Embedding]
        LLM[Gemini 2.5 Flash]
    end

    USER --> FE

    FE --> API

    API --> INGEST
    API --> RETRIEVE
    API --> GENERATE

    INGEST --> STORAGE
    INGEST --> EMBED
    INGEST --> VECTOR

    RETRIEVE --> VECTOR
    RETRIEVE --> EMBED

    GENERATE --> LLM

    API --> MONGO
```

---

# 3. Core System Flow

```mermaid
sequenceDiagram

    participant U as User
    participant FE as Frontend
    participant BE as Backend
    participant AI as Gemini
    participant DB as Vector DB

    U->>FE: Upload PDF

    FE->>BE: Send PDF

    BE->>BE: Extract Text + BBoxes
    BE->>AI: Generate Embeddings
    AI-->>BE: Vector Embeddings

    BE->>DB: Store Chunks + Vectors

    U->>FE: Ask Question
    FE->>BE: User Query

    BE->>AI: Embed Query
    AI-->>BE: Query Vector

    BE->>DB: Similarity Search
    DB-->>BE: Relevant Chunks

    BE->>AI: Generate Grounded Answer
    AI-->>BE: Response + Citations

    BE-->>FE: Structured Response

    FE-->>U: Highlight Source in PDF
```

---

# 4. PDF Ingestion Architecture

The ingestion pipeline transforms raw PDFs into semantically retrievable chunks.

## Ingestion Pipeline

```mermaid
flowchart LR

    PDF[Uploaded PDF]

    EXTRACT[PyMuPDF Extraction]

    CLEAN[Text Normalization]

    CHUNK[Chunking Engine]

    EMBED[Embedding Generation]

    STORE[Vector Storage]

    PDF --> EXTRACT
    EXTRACT --> CLEAN
    CLEAN --> CHUNK
    CHUNK --> EMBED
    EMBED --> STORE
```

---

# 5. Chunking Strategy

The architecture uses:

- bbox-aware chunking,
- page-isolated segmentation,
- semantic overlap preservation.

## Chunk Formation Logic

```mermaid
flowchart TB

    SPANS[Extracted Text Spans]

    SORT[Layout Sorting]

    MERGE[Merge Nearby Blocks]

    LIMIT[Chunk Size Threshold]

    OVERLAP[Apply Overlap]

    OUTPUT[Final Chunks]

    SPANS --> SORT
    SORT --> MERGE
    MERGE --> LIMIT
    LIMIT --> OVERLAP
    OVERLAP --> OUTPUT
```

---

# 6. Vector Retrieval Architecture

Semantic retrieval is powered by:

Gemini Embeddings + pgvector cosine similarity

---

## Retrieval Pipeline

```mermaid
flowchart LR

    QUERY[User Query]

    CONDENSE[Question Condensing]

    EMBED[Query Embedding]

    SEARCH[Cosine Similarity Search]

    TOPK[Top-K Chunk Selection]

    QUERY --> CONDENSE
    CONDENSE --> EMBED
    EMBED --> SEARCH
    SEARCH --> TOPK
```

---

# 7. RAG Generation Pipeline

The system follows a strict Retrieval-Augmented Generation workflow.

```mermaid
flowchart TB

    QUESTION[User Question]

    CONTEXT[Retrieved Chunks]

    HISTORY[Conversation History]

    PROMPT[Grounded Prompt Builder]

    LLM[Gemini 2.5 Flash]

    RESPONSE[Answer + Citations]

    QUESTION --> PROMPT
    CONTEXT --> PROMPT
    HISTORY --> PROMPT

    PROMPT --> LLM
    LLM --> RESPONSE
```

---

# 8. Citation Grounding Architecture

A core differentiator of the system is exact source grounding.

Each chunk stores:

- page number,
- bounding box,
- dimensions,
- source snippet.

---

## Citation Highlight Flow

```mermaid
sequenceDiagram

    participant U as User
    participant FE as Frontend
    participant PDF as PDF Viewer

    U->>FE: Click Citation

    FE->>PDF: Locate Page

    PDF->>PDF: Scroll To Page

    PDF->>PDF: Render Highlight Overlay

    PDF-->>U: Pulse Highlight
```

---

# 9. Storage Architecture

```mermaid
flowchart LR

    subgraph MongoDB
        USERS[Users]
        CHATS[Chats]
        META[PDF Metadata]
    end

    subgraph Supabase Storage
        FILES[Raw PDFs]
    end

    subgraph pgvector
        VECTORS[Embeddings]
        BBOX[BBox Metadata]
    end
```

---

# 10. Backend Internal Architecture

```mermaid
flowchart TB

    ROUTES[API Routes]

    AUTH[Authentication]

    INGESTION[Ingestion Engine]

    CHAT[Chat Engine]

    VECTOR[Vector Store]

    GEMINI[Gemini Client]

    ROUTES --> AUTH
    ROUTES --> INGESTION
    ROUTES --> CHAT

    CHAT --> VECTOR
    CHAT --> GEMINI

    INGESTION --> GEMINI
    INGESTION --> VECTOR
```

---

# 11. Authentication Flow

```mermaid
sequenceDiagram

    participant U as User
    participant FE as Frontend
    participant BE as Backend

    U->>FE: Login

    FE->>BE: Credentials

    BE->>BE: Verify Password

    BE-->>FE: JWT Token

    FE->>BE: Authorized Requests

    BE->>BE: Validate JWT
```

---

# 12. Deployment Architecture

```mermaid
flowchart LR

    VERCEL[Vercel Frontend]

    RENDER[Render Backend]

    MONGO[(MongoDB Atlas)]

    SUPA[(Supabase)]

    GEMINI[Gemini API]

    VERCEL --> RENDER

    RENDER --> MONGO
    RENDER --> SUPA
    RENDER --> GEMINI
```

---

# 13. System Design Principles

## Scalability

- stateless backend,
- persistent vector database,
- externalized storage architecture.

---

## Reliability

- retry/backoff embedding architecture,
- persistent cloud storage,
- retrieval fallback mechanisms.

---

## Grounded Generation

- strict context-only answering,
- citation enforcement,
- hallucination refusal pipeline.

---

## Performance

- batched embeddings,
- cosine vector indexing,
- top-k retrieval optimization,
- chunk overlap preservation.

---

# 14. Future Architecture Extensions

```mermaid
flowchart LR

    OCR[OCR Support]

    HYBRID[Hybrid Retrieval]

    STREAM[Streaming Responses]

    MULTI[Multi-PDF Search]

    OCR --> HYBRID
    HYBRID --> STREAM
    STREAM --> MULTI
```

---

# 15. UI Showcase

## Landing Page

<p align="center">
  <img src="./images/home.png" alt="Landing Page" width="100%" />
</p>

---

## Main Query Interface

<p align="center">
  <img src="./images/query.png" alt="Main Query Interface" width="100%" />
</p>
