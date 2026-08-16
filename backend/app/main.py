import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import auth, courses, documents, examination, teaching, tutoring

logging.basicConfig(level=logging.INFO)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Agentic Teacher Digital Twin (ATDT)",
    description=(
        "Teaching, Tutoring, and Examination channels grounded in a lecturer's "
        "own course documents via retrieval-augmented generation."
    ),
    version="0.1.0",
)

# Dev-friendly CORS; tighten the origin list before deploying anywhere shared.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(courses.router)
app.include_router(documents.router)
app.include_router(teaching.router)
app.include_router(tutoring.router)
app.include_router(examination.router)


@app.get("/health")
def health():
    from app.llm.dyon_llm import provider_name

    return {"status": "ok", "llm_provider": provider_name()}
