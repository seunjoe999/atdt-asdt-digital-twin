"""Document ingestion pipeline (thesis Chapter 3.3):

upload -> text extraction -> chunking -> embedding -> vector storage -> metadata
"""

from __future__ import annotations

from dataclasses import dataclass

from app.rag import chroma_store
from app.rag.embeddings import Embedder

CHUNK_SIZE = 1200  # characters (~roughly 300 tokens; keeps this dependency-free)
CHUNK_OVERLAP = 150


@dataclass
class ExtractedPage:
    page_number: int
    text: str


def extract_text(file_path: str, filename: str) -> list[ExtractedPage]:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf(file_path)
    if lower.endswith(".docx"):
        return _extract_docx(file_path)
    if lower.endswith(".txt"):
        return _extract_txt(file_path)
    raise ValueError(f"Unsupported file type: {filename} (use PDF, DOCX, or TXT)")


def _extract_pdf(file_path: str) -> list[ExtractedPage]:
    from pypdf import PdfReader

    reader = PdfReader(file_path)
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(ExtractedPage(page_number=i, text=text))
    return pages


def _extract_docx(file_path: str) -> list[ExtractedPage]:
    import docx

    document = docx.Document(file_path)
    text = "\n".join(p.text for p in document.paragraphs if p.text.strip())
    return [ExtractedPage(page_number=1, text=text)] if text.strip() else []


def _extract_txt(file_path: str) -> list[ExtractedPage]:
    with open(file_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    return [ExtractedPage(page_number=1, text=text)] if text.strip() else []


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """A simple recursive-ish character splitter: break on paragraph/sentence
    boundaries where possible, falling back to a hard cut, with overlap
    between consecutive chunks to preserve context across the boundary.
    """
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind("\n\n", start, end)
            if boundary == -1 or boundary <= start:
                boundary = text.rfind(". ", start, end)
            if boundary != -1 and boundary > start:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def ingest_document(
    *, course_id: int, document_id: int, collection_name: str, file_path: str, filename: str
) -> int:
    """Runs the full pipeline for one document; returns the chunk count."""
    pages = extract_text(file_path, filename)
    embedder = Embedder()

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []
    chunk_index = 0

    for page in pages:
        for chunk in chunk_text(page.text):
            ids.append(f"doc{document_id}_chunk{chunk_index}")
            documents.append(chunk)
            metadatas.append(
                {
                    "source_document": filename,
                    "page_number": page.page_number,
                    "chunk_index": chunk_index,
                    "course_id": course_id,
                    "document_id": document_id,
                }
            )
            chunk_index += 1

    if not documents:
        return 0

    embeddings = embedder.embed(documents)
    chroma_store.add_chunks(collection_name, ids, documents, embeddings, metadatas)
    return len(documents)
