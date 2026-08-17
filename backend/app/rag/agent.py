"""Retrieval + generation shared by the Tutoring, Teaching, and Examination
channels (thesis Chapter 3.5's "Agent Orchestrator", Figure 3.4's sequence).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.dyon_llm import generate
from app.rag import chroma_store
from app.rag.embeddings import Embedder


@dataclass
class RetrievedChunk:
    text: str
    source_document: str
    page_number: int | None
    chunk_index: int | None
    distance: float


def retrieve(collection_name: str, question: str, k: int = 5) -> list[RetrievedChunk]:
    embedder = Embedder()
    query_embedding = embedder.embed_one(question)
    result = chroma_store.query(collection_name, query_embedding, k=k)

    chunks: list[RetrievedChunk] = []
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0] if result.get("distances") else [0.0] * len(documents)

    for text, meta, dist in zip(documents, metadatas, distances):
        chunks.append(
            RetrievedChunk(
                text=text,
                source_document=meta.get("source_document", "unknown"),
                page_number=meta.get("page_number"),
                chunk_index=meta.get("chunk_index"),
                distance=dist,
            )
        )
    return chunks


def _build_context(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(No course material was retrieved. Say so plainly rather than guessing.)"
    parts = []
    for i, c in enumerate(chunks, start=1):
        parts.append(f"[Source {i}: {c.source_document}, page {c.page_number}]\n{c.text}")
    return "\n\n".join(parts)


async def answer_question(
    *,
    collection_name: str,
    question: str,
    persona: str = "a knowledgeable, patient course lecturer",
    history: str = "",
) -> tuple[str, list[RetrievedChunk]]:
    """The Tutoring Channel's RAG pipeline: retrieve -> assemble prompt -> generate."""
    chunks = retrieve(collection_name, question, k=5)
    context = _build_context(chunks)

    system_prompt = (
        f"You are {persona}, answering a student's question using ONLY the course "
        "material excerpts provided below. If the excerpts do not contain the "
        "answer, say clearly that the material does not cover this rather than "
        "inventing an answer. Reference sources as [Source N] when you use them. "
        "Guide the student toward understanding rather than just handing over a "
        "complete answer where the question looks like an assessment question.\n\n"
        f"COURSE MATERIAL:\n{context}"
    )
    user_prompt = f"{history}\nStudent question: {question}" if history else f"Student question: {question}"

    answer = await generate(system_prompt, user_prompt)
    return answer, chunks


async def generate_teaching_material(
    *, collection_name: str, material_type: str, topic: str, instructions: str, persona: str
) -> tuple[str, list[RetrievedChunk]]:
    query = topic or f"key concepts for a {material_type.replace('_', ' ')}"
    chunks = retrieve(collection_name, query, k=8)
    context = _build_context(chunks)

    type_instructions = {
        "lesson_plan": "Produce a structured lesson plan with learning objectives, "
        "a sequence of teaching activities with rough timings, and a wrap-up.",
        "summary": "Produce a clear, well-organised topic summary with headings.",
        "revision_notes": "Produce concise revision notes as bullet points grouped by sub-topic.",
        "practice_questions": "Produce a set of practice questions (mixed difficulty) with "
        "an answer key at the end.",
    }
    instruction = type_instructions.get(material_type, "Produce well-structured teaching material.")

    system_prompt = (
        f"You are {persona}, preparing {material_type.replace('_', ' ')} material for your own "
        "course, grounded in the course material excerpts below. Do not invent facts not "
        f"supported by the excerpts. {instruction}\n\n"
        f"COURSE MATERIAL:\n{context}"
    )
    user_prompt = f"Topic: {topic or '(general course coverage)'}\nAdditional instructions: {instructions or '(none)'}"

    content = await generate(system_prompt, user_prompt)
    return content, chunks
