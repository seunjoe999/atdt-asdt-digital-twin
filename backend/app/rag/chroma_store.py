from __future__ import annotations

from functools import lru_cache

import chromadb

from app.config import get_settings


@lru_cache
def get_client() -> chromadb.ClientAPI:
    settings = get_settings()
    return chromadb.PersistentClient(path=settings.chroma_dir)


def get_or_create_collection(name: str):
    return get_client().get_or_create_collection(name=name)


def add_chunks(
    collection_name: str,
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> None:
    if not ids:
        return
    collection = get_or_create_collection(collection_name)
    collection.add(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)


def query(collection_name: str, query_embedding: list[float], k: int = 5) -> dict:
    collection = get_or_create_collection(collection_name)
    if collection.count() == 0:
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
    return collection.query(
        query_embeddings=[query_embedding], n_results=min(k, collection.count())
    )


def delete_document_chunks(collection_name: str, document_id: int) -> None:
    collection = get_or_create_collection(collection_name)
    collection.delete(where={"document_id": document_id})
