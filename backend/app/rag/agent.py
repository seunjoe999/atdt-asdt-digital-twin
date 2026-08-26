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


async def generate_teaching_advice(
    *,
    collection_name: str,
    persona: str,
    student_name: str,
    overall_mastery: float,
    open_gaps: int,
    topics: list[tuple[str, float]],
) -> str:
    """The Teacher Twin's advice for one specific student — grounded in the
    same course material as tutoring/materials, but addressed to the
    lecturer: what to actually do about this student's measured gaps.
    """
    weak_topics = [t for t, m in topics if m < 0.8]
    query = ", ".join(weak_topics) if weak_topics else "course fundamentals"
    chunks = retrieve(collection_name, query, k=6)
    context = _build_context(chunks)

    topic_lines = "\n".join(f"- {t}: {round(m * 100)}% mastery" for t, m in topics) or "(no graded assessments yet)"

    system_prompt = (
        f"You are {persona}'s Teacher Twin, advising the lecturer on how to help one specific "
        "student, using ONLY the course material excerpts below to ground any content "
        "recommendations. Give concrete, actionable advice: which topics to revisit, what "
        "kind of intervention fits the severity, and reference the course material by "
        "[Source N] where relevant. Keep it to a short paragraph plus a few bullet points. "
        "Do not invent facts not supported by the excerpts.\n\n"
        f"COURSE MATERIAL:\n{context}"
    )
    user_prompt = (
        f"Student: {student_name}\n"
        f"Overall mastery: {round(overall_mastery * 100)}%\n"
        f"Open gaps: {open_gaps}\n"
        f"Per-topic mastery:\n{topic_lines}\n\n"
        "What should this lecturer do for this student?"
    )

    return await generate(system_prompt, user_prompt)
