# Interview Notes — Financial Document Intelligence Platform

> These notes are updated at each phase. Answers are based on **our actual implementation**, not generic theory.

---

## Phase 1 Questions Covered

### 1. What problem does this system solve?

Financial analysts spend hours reading dense PDFs — annual reports, 10-Ks, earnings releases — to answer questions like "What were the top risks mentioned by Apple?" or "How did revenue change year-over-year?"

This platform lets you upload those PDFs, then ask natural-language questions. It retrieves the relevant document sections and uses a locally-running LLM (Gemma 3 4B) to generate answers grounded in citations with document name and page number.

**Key distinction:** The LLM answers from retrieved document evidence, not from its training knowledge. This is critical for financial accuracy — you wouldn't trust a model's internal knowledge of Apple's FY2024 revenue.

---

### 2. Explain the architecture.

```
User → React Frontend (Vite, port 5173)
           ↓ REST calls
FastAPI Backend (port 8000)
    ├── /api/v1/companies    — company registry
    ├── /api/v1/documents    — upload, status, extraction
    ├── /api/v1/query        — RAG question answering
    └── /api/v1/health       — liveness + DB readiness

PostgreSQL + pgvector (Docker, port 5432)
    ├── companies
    ├── documents            (with processing status lifecycle)
    ├── document_pages       (raw + cleaned text per page)
    ├── document_chunks      (text chunks + VECTOR(768) embeddings)
    └── financial_metrics    (structured extracted values)

Ollama (local, port 11434)
    ├── gemma3:4b            → answer generation (RAG)
    └── nomic-embed-text     → embedding generation
```

The backend follows a layered architecture: API routes → service layer → domain logic → repository/DB. No business logic lives in route functions.

---

### 3. What happens after uploading a PDF?

1. **Validation** — MIME type checked, PDF magic bytes (`%PDF`) verified, file size limit enforced.
2. **Saved** — Written to `uploads/` with a UUID-based filename (never user-controlled path).
3. **DB record created** — Status set to `UPLOADED`.
4. **Processing triggered** (Phase 2+) — Status moves through: `EXTRACTING → CHUNKING → EMBEDDING → READY`.
5. **Extraction** — PyMuPDF reads page by page; each page's text is stored in `document_pages`.
6. **Chunking** — Text is split into ~600-word chunks with ~80-word overlap; stored in `document_chunks`.
7. **Embedding** — Each chunk is embedded by nomic-embed-text; the vector stored in the `embedding` column.
8. **Ready** — Status set to `READY`; document is now queryable.

---

### 4. Why chunk documents?

You can't pass an entire 200-page annual report to a language model — models have a **context window limit** (maximum tokens they can process at once).

Chunking breaks the document into retrievable pieces. When a question is asked, only the 5 most relevant chunks (top-k) are retrieved and passed to the model — not the full document.

**The tradeoff:**
- Smaller chunks → more precise retrieval, but less context per chunk
- Larger chunks → more context, but noisier retrieval (more irrelevant content in top-k)
- We start with ~600 words, which is a commonly-used balance for financial documents.

---

### 5. How did you choose chunk size?

We started at 600 words (configurable via `RAG_CHUNK_SIZE` in `.env`).

Reasoning:
- Financial documents have dense paragraphs; 600 words typically contains 1–3 complete concepts.
- We want each chunk to be semantically self-contained (a complete risk factor, a financial table section).
- 600 words is roughly 800 tokens — well within Gemma 3 4B's context when combined with top-5 chunks.

The configuration allows adjustment: if retrieval quality is poor, increase chunk size for more context; if precision is poor, decrease it. This is evaluated in Phase 11.

---

### 6. What is an embedding?

An embedding is a **dense vector** (a list of numbers) that represents the meaning of a piece of text in a mathematical space.

Texts with similar meanings produce vectors that are geometrically close together.

For example:
- "revenue growth" and "increase in net sales" → very close vectors
- "revenue growth" and "operating risks" → more distant vectors

This is how we do semantic retrieval — instead of keyword matching, we measure vector proximity.

Our embedding model (nomic-embed-text) converts each chunk into a 768-dimensional vector, stored in the `embedding` column of `document_chunks` using pgvector's `VECTOR(768)` type.

---

### 18. Why FastAPI?

- **Async-native**: Uses Python's `asyncio` natively — database queries don't block the event loop.
- **Pydantic v2**: Request validation and response serialization with type safety.
- **Auto-generated docs**: `/docs` and `/redoc` are generated automatically from type hints — useful during development.
- **Performance**: Comparable to Node.js for I/O-bound workloads (which this is — DB queries, HTTP calls to Ollama).
- **Industry standard**: Widely used in data/AI/ML backends.

---

### 19. Why PostgreSQL?

- **Mature ACID database**: Reliable transactions for document processing status updates.
- **pgvector extension**: Adds native vector similarity search — no separate vector database needed.
- **One system for two concerns**: Stores both relational data (companies, documents, metrics) and vector embeddings in the same database. Simplifies operations, backups, and queries.
- **SQL + vector in one query**: Can filter by company/document AND rank by vector similarity in a single SQL statement.

---

### 20. Why keep vectors in PostgreSQL instead of a dedicated vector DB?

Dedicated vector databases (Pinecone, Weaviate, Qdrant) optimize purely for vector search at very large scale.

For our scale (tens to hundreds of documents), PostgreSQL + pgvector is sufficient and has several advantages:
- **No extra infrastructure**: No second database to deploy, back up, or query separately.
- **Relational joins work**: Can filter `WHERE document_id = X` before the vector search, combining relational and semantic filtering efficiently.
- **Lower operational complexity**: One database backup covers everything.
- **Simpler code**: Single connection pool, single transaction boundary.

The tradeoff: at millions of vectors, pgvector's exact nearest-neighbor search becomes slow and HNSW indexing is needed. Dedicated vector DBs are architecturally optimized for that scale.

---

### 27. Why use local LLMs?

- **Privacy**: Financial documents may contain material non-public information. Sending them to OpenAI or Anthropic has legal/compliance implications.
- **Cost**: No per-token API cost at scale.
- **Latency control**: No internet dependency; latency is predictable.
- **Portfolio signal**: Demonstrates ability to deploy AI in constrained or air-gapped environments — valuable for fintech/institutional roles.

The tradeoff: Gemma 3 4B is significantly less capable than GPT-4 or Claude 3 Opus. Answer quality is lower, especially for complex multi-hop reasoning. This is acknowledged, not hidden.

---

### 28. What limitations does Gemma 3 4B create?

- **Reasoning depth**: Struggles with complex multi-document comparison or numerical reasoning chains.
- **Instruction following**: Less reliably follows structured output format constraints.
- **Context utilization**: May not use all 5 retrieved chunks effectively.
- **Hallucination rate**: Higher than frontier models, even with grounding instructions.

Mitigations in our design:
- Explicit system prompt: "use ONLY the supplied context."
- Citation validation: Page numbers come from retrieved chunks, not LLM output.
- Python handles arithmetic: Growth rates, ratios, differences are computed in code, not by the LLM.

---

## Phase 2 Questions Covered

### 7. Why PyMuPDF over PyPDF, pdfplumber, or PDFMiner?

- **Performance**: PyMuPDF is powered by MuPDF (a high-performance C rendering library). It processes large 200+ page 10-Ks up to 10–20x faster than pure-Python parsers like PyPDF or PDFMiner.
- **Layout & Reading Order**: It handles multi-column financial layouts and text flows with high fidelity compared to simpler extractors.
- **Memory Footprint**: Page-by-page streaming loads only the active page into memory, keeping the memory footprint minimal even for 100MB+ filings.
- **Robustness**: Handles corrupted stream objects and non-standard font encodings gracefully.

---

### 8. Why store raw and cleaned pages in `document_pages` instead of going straight to chunks?

1. **Page-Level Provenance**: Financial analysts must verify extracted facts against exact page numbers. Storing pages creates an immutable intermediate representation.
2. **Decoupled Pipelines**: If we want to experiment with different chunking sizes (e.g., 300 words vs 600 words vs semantic section chunking), we can re-chunk from database rows without re-parsing raw PDF binaries from disk.
3. **Extraction Quality Auditing**: Makes it straightforward to inspect page text, detect scanned/blank pages (`is_empty=True`), and verify OCR needs.

---

### 9. How does the system handle scanned or image-only PDF pages?

- During page extraction, the text layer is parsed. If `len(cleaned_text) == 0`, the page is marked with `is_empty = True`.
- In V1, machine-readable text is required. Empty pages are tracked so the system doesn't generate empty embeddings.
- In Phase 12+, an OCR fallback (e.g., Tesseract or cloud vision API) can specifically target pages where `is_empty == True`.

---

*This file grows with each phase. After Phase 7 (full RAG), all 35 interview questions will have detailed, implementation-specific answers.*
