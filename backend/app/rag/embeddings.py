"""Embedding backend: OpenAI's text-embedding-3-small (per the thesis) when an
API key is configured, otherwise a dependency-free offline embedder so
ingestion and retrieval still work end to end for a demo without a key.
"""

from __future__ import annotations

import hashlib
import math

from app.config import get_settings

_OFFLINE_DIM = 256


def _offline_embed(text: str) -> list[float]:
    """A deterministic hashing bag-of-words vector.

    Not semantically meaningful the way a trained embedding model is, but it
    is stable (same text -> same vector) and gives shared vocabulary between a
    question and a relevant chunk a nonzero cosine similarity, which is enough
    to exercise the whole pipeline without any external service.
    """
    vec = [0.0] * _OFFLINE_DIM
    for word in text.lower().split():
        idx = int(hashlib.md5(word.encode()).hexdigest(), 16) % _OFFLINE_DIM
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class Embedder:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = None
        if self._settings.openai_api_key:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._settings.openai_api_key)

    @property
    def is_offline(self) -> bool:
        return self._client is None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._client is None:
            return [_offline_embed(t) for t in texts]
        resp = self._client.embeddings.create(model="text-embedding-3-small", input=texts)
        return [d.embedding for d in resp.data]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
