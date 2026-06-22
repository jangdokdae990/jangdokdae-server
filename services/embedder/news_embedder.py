"""뉴스 임베딩 — 전처리 통과분을 제목+본문 가중평균으로 벡터화해 news.embedding에 채운다.

재설계(2026-06-18, bake-off 2026-06-22 확정): 입력은 **제목 + 본문 청크 mean pooling 가중평균**.
임베딩 직전에 trafilatura로 본문을 fetch(`follow_redirects`)·정제·overlap 청킹하고, 청크 mean
pooling 벡터를 제목 벡터와 α 가중평균(α=`EMBED_TITLE_WEIGHT`, 각 L2 정규화 후 결합)한다. 본문은
임베딩 입력 산출 후 폐기(DB 영구저장 금지). 본문 fetch 실패 기사는 제목만으로 폴백한다.

is_filtered=FALSE AND embedding IS NULL만 집어가므로 재실행해도 미임베딩분만 처리한다(멱등).
"""

import asyncio
import logging
from collections import defaultdict
from typing import cast
from urllib.parse import urlparse

import httpx
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.queries import get_unembedded_news, save_news_embeddings
from services.analyzer.article_fetcher import fetch_article_body
from services.embedder.embedding_client import EmbeddingClient, LazyClientMixin
from services.preprocessor.body_processor import chunk_with_overlap, clean_body

logger = logging.getLogger(__name__)

# 본문 fetch 동시성 — 매체 부하·차단 회피(수집기 RSS 폴링과 동일한 보수적 상한).
FETCH_CONCURRENCY = 5
# 한 매체(도메인)에 대한 동시 요청 상한 — 특정 매체 rate limit·차단 회피(운영 가드).
PER_DOMAIN_CONCURRENCY = 2
FETCH_TIMEOUT = 10.0


def _domain(url: str) -> str:
    """URL에서 도메인(netloc)을 뽑는다 — 도메인별 동시성 제한 키."""
    return urlparse(url).netloc


def _l2(matrix: np.ndarray) -> np.ndarray:
    """행별 L2 정규화."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return cast(np.ndarray, matrix / np.clip(norms, 1e-12, None))


def combine_title_body(
    title_vecs: np.ndarray, body_vecs: np.ndarray, alpha: float
) -> np.ndarray:
    """제목·본문 벡터를 가중평균 결합한다 — α·제목 + (1-α)·본문(각 L2 정규화 후, 결과도 L2).

    body_vecs의 NaN 행(본문 없음)은 제목 벡터로 폴백한다. 순수 함수(테스트 용이).
    """
    title = _l2(title_vecs)
    nan_rows = np.isnan(body_vecs).any(axis=1)
    body = np.where(nan_rows[:, None], title, _l2(np.nan_to_num(body_vecs)))
    return _l2(alpha * title + (1.0 - alpha) * body)


async def _fetch_bodies(urls: list[str]) -> list[str | None]:
    """URL별 본문을 정제해 반환. 실패·페이월·예산 초과는 None(title-only 폴백).

    운영 가드(설계 02 §8.4.1): 전역 동시성 + 도메인별 동시성 제한 + 전체 fetch 예산(deadline).
    예산을 넘기면 남은 기사는 fetch하지 않고 None으로 둬 파이프라인이 느린 매체에 묶이지 않게 한다.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + settings.fetch_budget_seconds
    global_sem = asyncio.Semaphore(FETCH_CONCURRENCY)
    domain_sems: dict[str, asyncio.Semaphore] = defaultdict(
        lambda: asyncio.Semaphore(PER_DOMAIN_CONCURRENCY)
    )

    async def one(client: httpx.AsyncClient, url: str) -> str | None:
        if loop.time() >= deadline:
            return None  # 예산 소진 — title-only
        try:
            async with global_sem, domain_sems[_domain(url)]:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return None
                raw = await asyncio.wait_for(
                    fetch_article_body(url, client=client), timeout=min(FETCH_TIMEOUT, remaining)
                )
        except Exception as exc:  # noqa: BLE001 — 건별 격리(wait_for TimeoutError 포함)
            logger.warning("본문 fetch 예외 url=%s err=%r", url, exc)
            return None
        return clean_body(raw) if raw else None

    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT, headers={"User-Agent": "jangdokdae-embed/1.0"},
        follow_redirects=True,
    ) as client:
        return list(await asyncio.gather(*(one(client, u) for u in urls)))


def _body_matrix(client: EmbeddingClient, bodies: list[str | None], dim: int) -> np.ndarray:
    """본문별 청크 mean pooling 행렬. 본문 없는 행은 NaN(combine에서 제목 폴백)."""
    chunks: list[str] = []
    owner: list[int] = []
    for i, body in enumerate(bodies):
        if not body:
            continue
        for c in chunk_with_overlap(body, settings.chunk_size, settings.chunk_overlap) or [body]:
            chunks.append(c)
            owner.append(i)

    out = np.full((len(bodies), dim), np.nan, dtype=np.float32)
    if chunks:
        cvecs = np.array(client.embed_documents(chunks, "CLUSTERING"), dtype=np.float32)
        owner_arr = np.array(owner)
        for i in range(len(bodies)):
            mask = owner_arr == i
            if mask.any():
                out[i] = cvecs[mask].mean(axis=0)
    return out


class NewsEmbedder(LazyClientMixin):
    """미임베딩 뉴스를 제목+본문 가중평균으로 배치 임베딩해 news.embedding에 저장한다."""

    async def embed_news(self, db: AsyncSession) -> int:
        """임베딩 대기 뉴스를 임베딩·저장하고 처리 건수를 반환한다.

        본문 fetch(네트워크)는 async, 임베딩(동기 블로킹)은 to_thread로 빼 루프를 막지 않는다.
        """
        rows = await get_unembedded_news(db)
        if not rows:
            return 0
        titles = [row.title for row in rows]
        bodies = await _fetch_bodies([row.url for row in rows])
        vectors = await asyncio.to_thread(self._embed_and_combine, titles, bodies)
        await save_news_embeddings(db, dict(zip((r.id for r in rows), vectors, strict=True)))
        body_ok = sum(1 for b in bodies if b)
        logger.info(
            "뉴스 임베딩 완료 count=%d 본문ok=%d/%d model=%s",
            len(rows), body_ok, len(rows), self.client.model_name,
        )
        return len(rows)

    def _embed_and_combine(self, titles: list[str], bodies: list[str | None]) -> list[list[float]]:
        """제목·본문을 임베딩해 가중평균 결합한 벡터 리스트를 반환한다(동기)."""
        title_vecs = np.array(self.client.embed_documents(titles, "CLUSTERING"), dtype=np.float32)
        body_vecs = _body_matrix(self.client, bodies, title_vecs.shape[1])
        combined = combine_title_body(title_vecs, body_vecs, settings.embed_title_weight)
        return cast(list[list[float]], combined.tolist())
