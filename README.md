# ATDT + ASDT — Digital Twin Classroom (MVP)

**Live demo:** https://frontend-bice-five-4nxmifmhej.vercel.app
(backends: [ATDT](https://atdt-backend.onrender.com/docs) /
[ASDT](https://asdt-backend.onrender.com/docs) — both on Render's free tier,
so the first request after ~15 min idle takes 30–60s to wake up; that's
normal, not a bug)

Repo: https://github.com/seunjoe999/atdt-asdt-digital-twin

A single webapp that demos both halves of the final year project together:
a **teacher** uploads course material, which the **ATDT** (Agentic Teacher
Digital Twin) ingests and teaches from; a **student** then learns through
their own **ASDT** (Agentic Student Digital Twin), which tracks their
mastery, detects gaps from real exam results, and negotiates remediation
with ATDT's Tutoring Channel on the student's behalf — real twin-to-twin
negotiation over HTTP, not simulated.

This file covers the ATDT service specifically (Teaching / Tutoring /
Examination channels, thesis Chapters 1–3), built on FastAPI + SQLAlchemy +
ChromaDB, with the LLM/agent layer supplied by
[`dyon`](https://github.com/lazy-monster/dyon) — a domain-agnostic Python
framework for agentic digital twins. See [`asdt/README.md`](asdt/README.md)
for the ASDT service, and **"Run the full webapp demo" below** for how the
two combine into one browser session with a Teacher view and a Student view.
It's scoped as an MVP that runs **without Docker or Neo4j** so it's runnable
today; the READMEs note exactly what to add for the fuller thesis
architecture (Postgres, Neo4j-backed knowledge graph).

## Status: verified running, including in a real browser

Both services have been installed, tested, and run live end to end — not
just reviewed. `pytest -q` passes in both. Beyond that, I drove the actual
unified webapp in a real Chrome tab through the full demo script: registered
a teacher, created a course, uploaded a `.txt` file and watched ATDT ingest
it, generated and published an assessment; then registered a student,
enrolled with the course code, asked a question through "Ask ASDT" (real
citation came back from ATDT's RAG pipeline), deliberately answered the quiz
wrong, watched the frontend auto-sync with ASDT and detect a gap, clicked
"Ask ASDT for help" to negotiate remediation, and read the resulting
Performance Report. That live run caught and fixed one real bug — see
`frontend/index.html`'s `negotiate()`/`loadGaps()` history for a bug where
the negotiation answer briefly appeared then got wiped by the immediately-
following gap-list reload; it's now cached client-side and re-injected on
every render. (Earlier in this project, the sandbox's Python install was
also corrupted — 0-byte `python.exe` — and had to be reinstalled first;
that's resolved too.)

## Run the full webapp demo

Three processes, one browser tab. From the repo root, in three terminals:

```bash
# 1. ATDT (Teaching/Tutoring/Examination) on :8000
cd backend && .venv\Scripts\activate && uvicorn app.main:app --port 8000

# 2. ASDT (student twin, negotiates with ATDT) on :8001
cd asdt/backend && .venv\Scripts\activate && uvicorn app.main:app --port 8001

# 3. Serve the frontend as a real page (not file://, which most browsers
#    block from making cross-origin fetch() calls to localhost APIs)
cd frontend && python -m http.server 8080
```

Open `http://localhost:8080` in a browser. Register once as a **Teacher**:
create a course, upload a PDF/DOCX/TXT, publish an assessment. Then register
a second account as a **Student** (a different email — log out first) and
use the course's enrolment code to enrol. The student view has four tabs:
**Ask ASDT** (free-form Q&A, routed through the student's own twin), **My
Learning** (sync progress, see mastery per topic, negotiate remediation on
any detected gap), **Assessments** (take a published quiz — submitting
auto-syncs ASDT), and **Performance Report** (the aggregated view of both).
Both API base URLs are editable at the top of the page if you run the
backends on different ports/hosts.

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

Interactive API docs are at `http://localhost:8000/docs`. For the full
webapp (this service + ASDT + the frontend, so you can actually click
through the teacher and student flows), see **"Run the full webapp demo"**
above.

## Known MVP scope cuts (documented, not hidden)

- **Frontend** is a single-page vanilla JS app (`frontend/index.html`), not
  the thesis's stated React/Next.js. It now covers both ATDT and ASDT in one
  page — a Teacher view (upload/generate/publish) and a Student view (Ask
  ASDT, My Learning with mastery + gap negotiation, take assessments,
  Performance Report) — and exercises every endpoint on both services, but
  isn't a polished UI. If the defense needs Next.js specifically, this is
  the piece to rebuild first — the API contracts (see each service's
  `/docs`) don't need to change.
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

## ASDT (Agentic Student Digital Twin)

Built as a separate service at [`asdt/`](asdt/) — its own FastAPI app, own
database, own venv, talking to this service only over HTTP (no shared code,
no shared secret). It reads a student's own attempt history via the new
`GET /courses/{id}/examination/my-attempts` endpoint added here, models
per-topic mastery, detects gaps, and negotiates remediation by calling this
service's Tutoring Channel with the student's own bearer token — real
twin-to-twin negotiation, verified against a live instance of this service.
See `asdt/README.md` for the full CDDT-layer mapping and documented scope
cuts (no Knowledge Graph yet, no ranked multi-candidate bidding, no NERDC/
Pidgin localisation).
