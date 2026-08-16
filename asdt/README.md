# ASDT — Agentic Student Digital Twin (MVP)

A separate FastAPI service that acts as a student's own agentic twin: it
tracks the student's per-topic mastery from their real ATDT results, detects
competency gaps, and **negotiates remediation with ATDT's Tutoring Channel
over real HTTP** — the "twin-to-twin negotiation" the ASDT thesis is built
around, working end to end against a live ATDT instance.

## What's implemented vs. the thesis

The ASDT thesis specifies a six-layer Cross-Domain Digital Twin (CDDT)
architecture (Acquisition & Tracking → Simulation → Analytics & Monitoring →
Reactive Control → Intelligent Control → Autonomous Control), a Contract-Net-
Protocol-style negotiation with ranked candidate bids, a Deep-Knowledge-
Tracing probabilistic student model, full NERDC curriculum alignment, and
Nigerian-context localisation (Pidgin English, low-bandwidth edge inference,
NDPR compliance). That's a full second thesis's worth of scope.

This MVP implements the four **lower** layers for real, end to end, and
documents the rest as future work rather than faking it:

| CDDT Layer (thesis 3.4.1) | This implementation |
|---|---|
| L1 — Acquisition & Tracking | `POST /asdt/sync` pulls the student's own real submitted attempts from ATDT (`GET /courses/{id}/examination/my-attempts`, added to ATDT for this) |
| L2 — Simulation | `app/gap_analysis.py::compute_mastery_by_topic` — a simple average-of-scores mastery model per topic, stored in `KnowledgeState` |
| L3 — Analytics & Monitoring | `gap_analysis.is_gap` / `severity` — mastery below `GAP_THRESHOLD` (default 0.6) opens a `GapEvent` |
| L4 — Reactive Control | `POST /asdt/negotiate` — event-driven: a gap triggers a real Tutoring Channel request to ATDT, and the response is logged as a `NegotiationRecord` |
| L5 — Intelligent Control (CollectionDT/CompositeDT/AggregateDT) | **Not implemented.** No cohort-level or cross-student coordination yet. |
| L6 — Autonomous Control | **Not implemented.** Negotiation currently only runs when a client calls `/asdt/negotiate`; nothing yet triggers it unprompted on gap detection. Straightforward next step: call negotiate automatically from inside `/asdt/sync` when a new gap is opened. |

Other documented scope cuts:
- **Negotiation is single-proposer, not ranked bidding.** The thesis's
  Contract Net Protocol (2.4) has ATDT propose multiple ranked candidate
  interventions; this MVP asks once and accepts ATDT's one Tutoring Channel
  answer as the remediation. Extending this means ATDT offering several
  material types (a summary, a practice set, a tutor conversation) and ASDT
  picking the best one — a natural next increment, not a redesign.
- **No Knowledge Graph.** Mastery is a flat per-topic average, not a graph of
  curriculum concepts and prerequisites. ATDT's own documented (unbuilt)
  Neo4j knowledge-graph upgrade path (see the top-level README) is the
  natural shared foundation for both twins' Simulation layers.
- **No NERDC curriculum codes, no Pidgin English, no edge/quantized
  inference, no NDPR-specific encryption.** `Assessment.topic` stands in for
  a real curriculum taxonomy.

## The trust model (thesis 1.5's "who represents the student?")

ASDT holds **no password, no JWT secret, and no shared database with ATDT**.
Every request to ASDT carries the student's own ATDT bearer token; ASDT
forwards that exact token to ATDT for every call it makes on the student's
behalf (`app/atdt_client.py`), and resolves identity by asking ATDT's own
`GET /auth/me` rather than decoding the token itself. From ATDT's point of
view, ASDT can never do anything the student couldn't already do by calling
ATDT directly — it just automates the noticing and the asking. A production
system would likely narrow this to a short-lived, scope-limited delegation
token instead of the full session token; that's a documented next step, not
implemented here.

## Setup

```bash
cd asdt/backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

`ATDT_BASE_URL` in `.env` must point at a running ATDT instance (see
`../../backend/README` section of the top-level README) — ASDT has nothing
useful to do without it.

```bash
pytest -q          # unit tests, ATDT itself replaced by a monkeypatched fake
uvicorn app.main:app --reload --port 8001
```

The test suite (`tests/test_negotiation.py`) exercises the full lifecycle —
sync → gap detection → negotiate → report → resync → gap resolution —
without a live ATDT. I additionally ran the same lifecycle by hand against a
**real running ATDT instance** (both servers started, real HTTP calls
between them, real ChromaDB-grounded Tutoring Channel answer with real
citations) to confirm the integration itself works, not just the mocks.

## API

| Endpoint | Purpose |
|---|---|
| `POST /asdt/sync` `{course_id}` | Pull fresh attempts from ATDT, recompute mastery, open/resolve gaps |
| `GET /asdt/gaps?course_id=` | This student's gap history for a course |
| `POST /asdt/negotiate` `{gap_event_id}` | Ask ATDT's Tutoring Channel for remediation on one gap, log the exchange |
| `GET /asdt/report?course_id=` | The "Generate Performance Report" use case (thesis Figure 3.1) |

All four require `Authorization: Bearer <ATDT student token>`.
