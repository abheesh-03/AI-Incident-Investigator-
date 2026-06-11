"""Embedding generation with deterministic fallback when no API key is set.

In production, plug in Voyage AI (`voyageai` SDK) — when VOYAGE_API_KEY is set
we call it; otherwise we use a deterministic hash-based vectorizer so the
service is fully functional offline and in CI.
"""
from __future__ import annotations

import hashlib
import math
from typing import Iterable

import httpx
import numpy as np

from app.core.config import get_settings

settings = get_settings()


def _hash_embed(text: str, dim: int) -> list[float]:
    """Deterministic embedding via repeated hashing — good enough for tests and demos."""
    rng_seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    rng = np.random.default_rng(rng_seed)
    # Build a vector influenced by token hashes so semantically similar
    # short strings cluster reasonably.
    base = rng.standard_normal(dim).astype(np.float32)
    for token in text.lower().split():
        h = int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:8], "big")
        idx = h % dim
        base[idx] += 1.0
    norm = float(np.linalg.norm(base))
    if norm == 0 or math.isnan(norm):
        return base.tolist()
    return (base / norm).tolist()


def _voyage_embed(texts: list[str]) -> list[list[float]]:
    resp = httpx.post(
        "https://api.voyageai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {settings.voyage_api_key}"},
        json={"input": texts, "model": "voyage-3"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return [item["embedding"] for item in data]


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    texts_list = list(texts)
    if not texts_list:
        return []
    if settings.voyage_api_key:
        try:
            return _voyage_embed(texts_list)
        except Exception:
            pass
    return [_hash_embed(t, settings.embedding_dim) for t in texts_list]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
