# ATDT — Agentic Teacher Digital Twin (MVP)

A working implementation of the **Teaching / Tutoring / Examination** channels
described in the ATDT thesis (Chapters 1–3), built on FastAPI + SQLAlchemy +
ChromaDB, with the LLM/agent layer supplied by
[`dyon`](https://github.com/lazy-monster/dyon) — a domain-agnostic Python
framework for agentic digital twins.

This is the ATDT half of the two-system final year project (ATDT + ASDT). It
is scoped as an MVP that runs **without Docker or Neo4j** so it's runnable
today; the README notes exactly what to add for the fuller thesis
architecture (Postgres, Neo4j-backed knowledge graph) and for ASDT.

## ⚠️ Not yet run in this environment

I could not execute or test this code myself: the sandbox this was built in
has no working Python interpreter (the installed Python 3.11 executable is
corrupted) and no Node.js. Everything below follows FastAPI/SQLAlchemy/
ChromaDB/dyon's documented APIs carefully, and a smoke test (`tests/
test_smoke.py`) exercises the full flow end to end using dyon's offline LLM
provider (no key needed). **Please run the smoke test first** after setup —
that's the fastest way to catch anything that slipped through review.

## How the pieces map to the thesis

| Thesis concept (Chapter 3) | This implementation |
|---|---|
| Document ingestion pipeline (3.3) | `app/rag/ingest.py` — pypdf/python-docx/txt extraction → chunking → embeddings → ChromaDB |
| Database schema (3.4) | `app/models.py` — same entities as Figure 3.3 (User, Course, Enrollment, Document, TeachingMaterial, Conversation, Message, Assessment, Question, Attempt, Response) |
| Agent Orchestrator (3.5) | `app/llm/dyon_llm.py` — wraps `dyon.core.config.TwinConfig` + `dyon.intelligent.agent.build_llm`, so the LLM provider (OpenAI / Anthropic / Ollama / offline) is a `.env` setting, never a code change |
| Tutoring RAG pipeline (Figure 3.4) | `app/rag/agent.py::answer_question` + `app/routers/tutoring.py` |
| Examination workflow (Figure 3.5) | `app/rag/assessment_agent.py` (generate → validate → retry ×3) + `app/routers/examination.py` (review/edit → publish → deliver → auto-grade) |

### Why dyon, concretely

`dyon` is built for physical/sensor-driven twins (pumps, turbines — its
`TwinConfig.sensor_fields`, MQTT ingestion, and Neo4j-backed
`KnowledgeGraph`/`DiagnosticAgent` assume telemetry). That doesn't map onto a
course-tutoring domain, so rather than forcing the whole framework in, this
project uses the one piece that transfers cleanly and matters most: **dyon's
provider-agnostic LLM factory** (`build_llm`), which gives every channel here
the same guarantees dyon gives a physical twin's diagnostic agent — bounded
timeouts/retries, one `.env` var to switch OpenAI/Anthropic/Ollama, and a
zero-dependency `offline` provider for demos without a key. See
`app/llm/dyon_llm.py` for the full rationale in comments.

**Documented upgrade path** if you want more of dyon in the final
submission: dyon's `KnowledgeGraph` (Chapter 08 of dyon's own guide) is a
genuinely good fit for modelling *misconceptions* — `Component` → course
topic, `FailureMode` → common misconception, `Symptom` → a wrong-answer
pattern in a student's SAQ response, `MaintenanceAction` → the remediation
material to serve. That requires Neo4j (`dyon infra up --layers
intelligent`), which is why it's not wired in by default here — add it once
Docker is available, and it plugs into `assessment_agent.grade_saq`'s output.

## Setup

Requires **Python 3.11+**. No Docker needed for this MVP (SQLite +
ChromaDB's local persistent client).

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
copy .env.example .env        # Windows; `cp` on macOS/Linux
```

Edit `.env` if you want real LLM output instead of the offline placeholder —
set `DT_LLM__PROVIDER=openai`, `DT_LLM__MODEL=gpt-4o`, and
`DT_LLM__API_KEY=sk-...` (also set `OPENAI_API_KEY` to the same value, since
that one drives embeddings independently of dyon). Leaving both blank is
fine for a first run: every channel still works, generating clearly-labelled
`[offline model]` text instead of real completions.

### Run the tests first

```bash
pytest -q
```

This runs the full flow (register → create course → upload a document →
ingest → tutor Q&A with citations → generate teaching material → generate,
review, publish, and take an assessment → auto-grading) with the offline LLM
provider, so it needs no key and no network.

### Run the API

```bash
uvicorn app.main:app --reload
```

Then open `frontend/index.html` directly in a browser (no build step, no
Node needed) — it talks to `http://localhost:8000` by default (editable in
the page). Interactive API docs are at `http://localhost:8000/docs`.

## Known MVP scope cuts (documented, not hidden)

- **Frontend** is a single-page vanilla JS app, not the thesis's stated
  React/Next.js. It exercises every endpoint but isn't a polished UI. If the
  defense needs Next.js specifically, this is the piece to rebuild first —
  the API contract (see `/docs`) doesn't need to change.
- **Database** defaults to SQLite for zero-setup. Swap `DATABASE_URL` in
  `.env` to a `postgresql+psycopg://...` URL to match the thesis's stated
  Postgres, then `pip install psycopg[binary]`.
- **Knowledge graph / Neo4j** is not wired in (see "Why dyon" above).
- **Persona configuration** (thesis 3.5, "Teaching Persona") is currently
  a fixed string per request (`"the lecturer for {course.title}"`); a real
  `TeachingPersona` model (name/tone/style, editable by the lecturer) is the
  natural next addition — small, additive change to `models.py` +
  `rag/agent.py`.
- **RBAC** is role-only (lecturer/student), matching the thesis's two
  actors; per-course granular permissions beyond "own course" /
  "enrolled student" are out of scope.

## Next: ASDT (Agentic Student Digital Twin)

Not started yet. Per the ASDT abstract, it's a separate twin representing
*the student* — reasoning about their learning gaps and negotiating with
ATDT (e.g., requesting remediation material, flagging a misconception)
rather than just consuming ATDT's channels passively. The natural interface
point is `app/rag/assessment_agent.py::grade_saq`'s per-question feedback and
`Response.score` — an ASDT twin would read a student's `Attempt`/`Response`
history via a new read API on this backend and reason over it independently.
Recommend starting that as its own service (own repo or `asdt/` sibling
directory) that calls ATDT's API rather than importing its code directly,
matching the thesis's "twin-to-twin negotiation" framing.
