# Investment Research & Financial Document Intelligence Platform

> A production-style RAG system for analyzing financial documents — upload annual reports and ask natural-language questions answered with grounded citations.

[![Python](https://img.shields.io/badge/Python-3.13-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql)](https://postgresql.org)
[![pgvector](https://img.shields.io/badge/pgvector-0.8-green)](https://github.com/pgvector/pgvector)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker)](https://docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## Overview

This platform solves a real problem in investment research: financial documents are dense, long, and time-consuming to read. Analysts need to quickly answer questions like:

- *"What were the major risks mentioned by Apple?"*
- *"How did revenue change compared with the previous year?"*
- *"What does management say about AI-related investments?"*
- *"Compare the risk factors discussed by Company A and Company B."*

This system processes uploaded PDFs, generates semantic embeddings, and answers questions using **Retrieval-Augmented Generation (RAG)** — retrieving the relevant document sections and using a locally-running LLM to produce grounded answers with page citations.

**Key principle**: The LLM is never the source of truth. Documents are. Every answer is grounded in retrieved evidence.

---

## Features

| Feature | Status |
|---|---|
| PDF upload & validation | ✅ Phase 1 |
| Page-by-page text extraction (PyMuPDF) | 🔄 Phase 2 |
| Configurable chunking with overlap | 🔄 Phase 3 |
| Semantic embeddings via nomic-embed-text | 🔄 Phase 4 |
| pgvector similarity search | 🔄 Phase 5 |
| Gemma 3 4B answer generation | 🔄 Phase 6 |
| Full RAG pipeline with citations | 🔄 Phase 7 |
| React research dashboard | 🔄 Phase 8 |
| Structured financial metric extraction | 🔄 Phase 9 |
| Company comparison with charts | 🔄 Phase 10 |
| Retrieval quality evaluation | 🔄 Phase 11 |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  React Frontend                      │
│         (Vite + TypeScript, port 5173)               │
└──────────────────────┬──────────────────────────────┘
                       │ REST API
┌──────────────────────▼──────────────────────────────┐
│               FastAPI Backend                        │
│                  (port 8000)                         │
│                                                      │
│  /api/v1/companies  /api/v1/documents                │
│  /api/v1/query      /api/v1/health                   │
│                                                      │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │  Ingestion  │  │  RAG Pipeline│  │ Extraction │  │
│  │  Pipeline   │  │              │  │  (Metrics) │  │
│  │  PyMuPDF    │  │  Retriever   │  │            │  │
│  │  Chunker    │  │  Context     │  │  Pydantic  │  │
│  │  Embedder   │  │  Builder     │  │  Schemas   │  │
│  └─────────────┘  └──────────────┘  └────────────┘  │
└───────┬─────────────────────────────────┬────────────┘
        │                                 │
┌───────▼──────────────┐    ┌─────────────▼────────────┐
│  PostgreSQL + pgvector│    │   Ollama (local)          │
│  (Docker, port 5432)  │    │   (port 11434)            │
│                       │    │                           │
│  companies            │    │  gemma3:4b                │
│  documents            │    │  → RAG answer generation  │
│  document_pages       │    │                           │
│  document_chunks      │    │  nomic-embed-text         │
│  ├── VECTOR(768)      │    │  → semantic embeddings    │
│  financial_metrics    │    │                           │
└───────────────────────┘    └───────────────────────────┘
```

### RAG Pipeline

```
User Question
     ↓
Embed question (nomic-embed-text)
     ↓
pgvector cosine similarity search
     ↓
Top-K relevant chunks (with document + page metadata)
     ↓
Build structured evidence context [S1], [S2], [S3]...
     ↓
Construct grounded prompt (Gemma 3 4B)
     ↓
Parse answer + validate citations
     ↓
Return: answer + source list (document, page, excerpt)
```

---

## Technology Stack

### Backend
| Technology | Version | Purpose |
|---|---|---|
| Python | 3.13 | Runtime |
| FastAPI | 0.115 | Async web framework |
| SQLAlchemy | 2.0 | Async ORM |
| asyncpg | 0.30 | Async PostgreSQL driver |
| Alembic | 1.14 | Database migrations |
| PyMuPDF | 1.24 | PDF text extraction |
| pgvector | 0.3 | Vector similarity type |
| Pydantic | 2.10 | Validation + settings |
| httpx | 0.28 | Async HTTP client (Ollama) |

### Infrastructure
| Technology | Purpose |
|---|---|
| PostgreSQL 16 + pgvector | Relational + vector database |
| Docker Compose | Database containerization |
| Ollama | Local LLM runtime |
| Gemma 3 4B | Answer generation (Q4_K_M) |
| nomic-embed-text | Semantic embeddings (768-dim) |

### Frontend (Phase 8)
| Technology | Purpose |
|---|---|
| React + TypeScript | UI framework |
| Vite | Build tool |
| Recharts | Financial charts |

---

## Database Schema

```sql
companies
├── id (UUID PK)
├── name, ticker, sector
└── created_at

documents
├── id (UUID PK)
├── company_id → companies
├── original_filename, file_path
├── document_type, fiscal_year
├── page_count, file_size_bytes
├── processing_status  -- UPLOADED|EXTRACTING|CHUNKING|EMBEDDING|READY|FAILED
└── created_at, updated_at

document_pages
├── id (UUID PK)
├── document_id → documents
├── page_number
├── raw_text, cleaned_text
└── is_empty, char_count

document_chunks
├── id (UUID PK)
├── document_id → documents
├── page_number, chunk_index
├── content (TEXT)
├── embedding VECTOR(768)   ← pgvector column
└── token_count, created_at

financial_metrics
├── id (UUID PK)
├── document_id → documents
├── metric_name, metric_value
├── unit, currency, period
├── source_page, source_text   ← provenance preserved
└── confidence, needs_review
```

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | ≥ 3.11 | 3.13 recommended |
| Node.js | ≥ 18 | For frontend (Phase 8) |
| Docker Desktop | Latest | Must be running |
| Ollama | Latest | Must have `gemma3:4b` |

---

## Installation & Setup

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/financial-document-intelligence.git
cd financial-document-intelligence
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env if needed (defaults work for local development)
```

### 3. Start PostgreSQL + pgvector

> ⚠️ **Start Docker Desktop first**, then:

```bash
docker compose up -d
```

Verify it's healthy:
```bash
docker compose ps
# Should show: fintel_postgres  running  healthy
```

### 4. Set up Python environment

```bash
cd backend
python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 5. Run database migrations

```bash
# From backend/ directory with .venv activated
alembic upgrade head
```

Expected output:
```
INFO  [alembic.runtime.migration] Running upgrade -> 0001_initial, Initial schema
```

### 6. Install the embedding model

```bash
ollama pull nomic-embed-text
```

Verify Ollama models:
```bash
ollama list
# Should show: gemma3:4b and nomic-embed-text
```

### 7. Start the backend

```bash
# From backend/ directory
uvicorn app.main:app --reload --port 8000
```

Expected output:
```
INFO: Starting Financial Document Intelligence Platform v0.1.0
INFO: LLM model: gemma3:4b @ http://localhost:11434
INFO: Embedding model: nomic-embed-text (dim=768)
INFO: Uvicorn running on http://127.0.0.1:8000
```

### 8. Verify everything works

```bash
# Liveness check
curl http://localhost:8000/api/v1/health
# → {"status": "ok", "app": "...", "version": "0.1.0"}

# Database + pgvector check
curl http://localhost:8000/api/v1/health/db
# → {"status": "ok", "database": "connected", "pgvector": true}
```

Open the API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Running Tests

```bash
cd backend
pytest tests/ -v
```

Expected output:
```
tests/test_health.py::TestHealthEndpoint::test_health_returns_200 PASSED
tests/test_health.py::TestHealthEndpoint::test_health_returns_ok_status PASSED
tests/test_health.py::TestAPIStructure::test_docs_available PASSED
tests/test_health.py::TestAPIStructure::test_openapi_schema PASSED
...
```

---

## Local LLM Configuration

This project uses **Ollama** as the local LLM runtime. No cloud API keys required.

```
Ollama endpoint:  http://localhost:11434
LLM model:        gemma3:4b    (answer generation)
Embedding model:  nomic-embed-text  (semantic search)
```

The backend communicates with Ollama through an abstract `LLMClient` interface. Switching runtimes (e.g., to llama.cpp) requires only a new implementation of that interface — no changes to routes or business logic.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/health` | Liveness check |
| GET | `/api/v1/health/db` | Database + pgvector check |
| POST | `/api/v1/companies` | Create a company |
| GET | `/api/v1/companies` | List companies |
| GET | `/api/v1/companies/{id}` | Get company |
| POST | `/api/v1/documents/upload` | Upload PDF |
| GET | `/api/v1/documents` | List documents |
| GET | `/api/v1/documents/{id}` | Get document status |
| DELETE | `/api/v1/documents/{id}` | Delete document |
| POST | `/api/v1/query` | RAG question answering (Phase 7) |

Full interactive docs at `/docs` and `/redoc`.

---

## Example Queries (Phase 7+)

```json
POST /api/v1/query
{
    "question": "What were the major risks mentioned in the annual report?",
    "company_ids": ["<apple-company-id>"],
    "top_k": 5
}
```

Response:
```json
{
    "answer": "The annual report identifies several major risks... [S1] [S3]",
    "citations": [
        {
            "source_id": "S1",
            "document_id": "...",
            "filename": "Apple_2024_10K.pdf",
            "page": 37,
            "excerpt": "We face intense competition in all markets...",
            "similarity_score": 0.89
        }
    ]
}
```

---

## Development Phases

| Phase | Description | Status |
|---|---|---|
| 0 | Environment inspection | ✅ Complete |
| 1 | Project foundation, FastAPI, DB, Docker | ✅ **Current** |
| 2 | PDF upload, PyMuPDF extraction | 🔄 Next |
| 3 | Text cleaning, chunking with overlap | 📋 Planned |
| 4 | Embeddings + pgvector storage | 📋 Planned |
| 5 | Vector similarity retrieval | 📋 Planned |
| 6 | Gemma 3 4B integration | 📋 Planned |
| 7 | Full RAG pipeline + citations | 📋 Planned |
| 8 | React frontend dashboard | 📋 Planned |
| 9 | Structured financial metric extraction | 📋 Planned |
| 10 | Company comparison + charts | 📋 Planned |
| 11 | Retrieval evaluation framework | 📋 Planned |
| 12 | Polish, tests, interview prep | 📋 Planned |

---

## Limitations

- **LLM quality**: Gemma 3 4B (4-bit quantized) produces lower-quality answers than frontier models. Complex multi-hop reasoning may fail.
- **OCR**: V1 only processes machine-readable PDFs. Scanned documents require OCR (Phase 12+).
- **Scale**: Designed for tens to hundreds of documents, not enterprise scale.
- **No authentication**: This is a portfolio/research project, not a production system.
- **Table extraction**: Financial tables embedded as images in PDFs are not extracted in V1.

---

## Future Improvements

- [ ] Add OCR for scanned PDFs (Tesseract or cloud vision)
- [ ] HNSW indexing for faster vector search at scale
- [ ] Hybrid retrieval (pgvector + PostgreSQL full-text search)
- [ ] Reranking pass (cross-encoder) to improve retrieval precision
- [ ] User authentication and document access control
- [ ] Streaming response for long LLM answers
- [ ] Background document processing queue
- [ ] Excel/CSV financial data import

---

## Project Structure

```
financial-document-intelligence/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application
│   │   ├── api/                 # Route handlers
│   │   │   ├── health.py
│   │   │   ├── companies.py
│   │   │   ├── documents.py
│   │   │   └── query.py
│   │   ├── core/                # Config, logging, exceptions
│   │   ├── db/                  # SQLAlchemy models + session
│   │   ├── embeddings/          # EmbeddingProvider abstraction
│   │   └── llm/                 # LLMClient abstraction
│   ├── migrations/              # Alembic migration scripts
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                    # React + Vite (Phase 8)
├── docker-compose.yml           # PostgreSQL + pgvector
├── .env.example                 # All environment variables documented
├── INTERVIEW_NOTES.md           # Technical interview prep
└── README.md
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built as a portfolio project demonstrating RAG architecture, local LLM integration, pgvector semantic search, and full-stack financial data engineering.*
