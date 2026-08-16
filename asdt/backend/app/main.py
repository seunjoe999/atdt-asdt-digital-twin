import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import asdt

logging.basicConfig(level=logging.INFO)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Agentic Student Digital Twin (ASDT)",
    description=(
        "A student's own agentic twin: tracks per-topic mastery from ATDT "
        "results, detects competency gaps, and negotiates remediation with "
        "ATDT's Tutoring Channel on the student's behalf."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(asdt.router)


@app.get("/health")
def health():
    from app.config import get_settings

    return {"status": "ok", "atdt_base_url": get_settings().atdt_base_url}
