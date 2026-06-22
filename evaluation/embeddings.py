"""임베딩 행렬 빌더 — 모델별 제목/제목+본문 가중평균 임베딩을 만들고 디스크에 캐시한다.

입력 구성(설계 01 §3·§4 Gate 1 비교축):
    - "title"      : 제목 임베딩(L2 정규화)
    - "title_body" : 제목 벡터와 본문 청크 mean pooling을 가중평균(α·제목+(1−α)·본문),
                     각 L2 정규화 후 결합하고 결과를 다시 L2 정규화. 본문 없는 기사는 제목으로 폴백.

임베딩은 무거우므로 (goldset, 모델, 종류)별로 .npy 캐시 — 재실행은 즉시 끝난다.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import cast

import numpy as np

from services.embedder.embedding_client import embed_with
from services.preprocessor.body_processor import chunk_with_overlap

logger = logging.getLogger(__name__)

CACHE_DIR = Path("evaluation/cache")


def _l2(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return cast(np.ndarray, matrix / np.clip(norms, 1e-12, None))


def _slug(model: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]", "_", model)


def _cache_path(cache_dir: Path, tag: str, model: str, kind: str) -> Path:
    return cache_dir / f"{tag}__{_slug(model)}__{kind}.npy"


def title_vectors(model: str, items: list[dict], *, cache_dir: Path, tag: str) -> np.ndarray:
    path = _cache_path(cache_dir, tag, model, "title")
    if path.exists():
        return cast(np.ndarray, np.load(path))
    logger.info("제목 임베딩 model=%s n=%d", model, len(items))
    vecs = embed_with(model, [it["title"] for it in items], "CLUSTERING")
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(path, vecs)
    return vecs


def body_vectors(
    model: str,
    items: list[dict],
    *,
    cache_dir: Path,
    tag: str,
    chunk_size: int,
    overlap: int,
    dim: int,
) -> np.ndarray:
    """기사별 본문 청크 mean pooling 행렬. 본문 없는 행은 NaN(상위에서 제목으로 폴백)."""
    # 청크 파라미터가 본문 벡터를 바꾸므로 캐시 키에 포함한다(스윕 시 충돌 방지).
    path = _cache_path(cache_dir, tag, model, f"body_c{chunk_size}_o{overlap}")
    if path.exists():
        return cast(np.ndarray, np.load(path))

    chunks: list[str] = []
    owner: list[int] = []
    for i, it in enumerate(items):
        body = it.get("body")
        if not it.get("body_ok") or not body:
            continue
        for c in chunk_with_overlap(body, chunk_size, overlap) or [body]:
            chunks.append(c)
            owner.append(i)

    out = np.full((len(items), dim), np.nan, dtype=np.float32)
    if chunks:
        logger.info("본문 청크 임베딩 model=%s chunks=%d", model, len(chunks))
        cvecs = embed_with(model, chunks, "CLUSTERING")
        owner_arr = np.array(owner)
        for i in range(len(items)):
            mask = owner_arr == i
            if mask.any():
                out[i] = cvecs[mask].mean(axis=0)
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(path, out)
    return out


def build_input(
    model: str,
    items: list[dict],
    mode: str,
    *,
    cache_dir: Path = CACHE_DIR,
    tag: str,
    alpha: float = 0.3,
    chunk_size: int = 1000,
    overlap: int = 200,
) -> np.ndarray:
    """입력 구성 mode("title" | "title_body")에 따른 (n, d) 임베딩 행렬(L2 정규화)."""
    title = _l2(title_vectors(model, items, cache_dir=cache_dir, tag=tag))
    if mode == "title":
        return title
    if mode != "title_body":
        raise ValueError(f"알 수 없는 입력 mode: {mode}")

    body = body_vectors(
        model, items, cache_dir=cache_dir, tag=tag,
        chunk_size=chunk_size, overlap=overlap, dim=title.shape[1],
    )
    # 본문 없는 행(NaN)은 제목 벡터로 폴백, 나머지는 L2 정규화.
    nan_rows = np.isnan(body).any(axis=1)
    body_l2 = _l2(np.nan_to_num(body))
    body_final = np.where(nan_rows[:, None], title, body_l2)
    combined = alpha * title + (1.0 - alpha) * body_final
    return _l2(combined)
