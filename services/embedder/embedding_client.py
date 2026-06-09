"""임베딩 클라이언트 — 모델명으로 백엔드를 분기하는 단일 임베딩 경계.

설계 05 §11 비교 하니스의 `embed_with`와 동일한 분기를 프로덕션 임베더(news_embedder·
report_embedder)와 공유한다. 임베딩 모델이 미확정(05 §2.1)이라 `EMBED_MODEL` 값만 바꾸면
백엔드가 자동 전환되도록 분기 규칙을 한 곳에 모은다 — 하니스와 프로덕션이 같은 코드를 쓰면
"테스트에서 이긴 모델"과 "실제로 쓰는 모델"이 어긋날 위험이 없다.

분기 규칙(설계 05 §11):
    - "gemini"로 시작 → Vertex AI(관리형). gemini-embedding-001은 MRL로 EMBED_DIM 차원으로
      무손실 절단(3072→768). project/location 설정이 있어야 호출된다.
    - 그 외(nlpai-lab/KURE-v1, jhgan/ko-sroberta-multitask 등) → HuggingFace 로컬 로딩.

task type은 Vertex 전용 신호다(05 §7 RAG vs 클러스터링). HuggingFace 백엔드는 task type
개념이 없어 무시한다.
"""

import logging
from typing import Literal

import numpy as np
from langchain_core.embeddings import Embeddings

from app.config import settings

logger = logging.getLogger(__name__)

# Vertex 임베딩 task type — 같은 텍스트도 용도에 맞춰 임베딩 공간을 최적화한다.
# 뉴스 제목 클러스터링은 CLUSTERING, 사업보고서 RAG는 문서=RETRIEVAL_DOCUMENT·쿼리=RETRIEVAL_QUERY.
EmbedTaskType = Literal[
    "CLUSTERING", "RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY", "SEMANTIC_SIMILARITY"
]

_GEMINI_PREFIX = "gemini"


def is_vertex_model(model_name: str) -> bool:
    """관리형(Vertex) 분기 여부 — gemini 계열만 Vertex, 나머지는 HuggingFace."""
    return model_name.startswith(_GEMINI_PREFIX)


class EmbeddingClient:
    """모델명으로 백엔드를 고른 임베딩 클라이언트. 한 모델당 한 인스턴스를 재사용한다.

    모델 로딩(특히 HuggingFace는 수백 MB 가중치 로딩)이 무거우므로 호출마다 새로 만들지 말고
    인스턴스를 단계 수명 동안 보관한다. dim은 Vertex(MRL) 절단에만 쓰이고, HuggingFace 모델은
    네이티브 차원(KURE 1024·ko-sroberta 768)을 그대로 쓰므로 무시된다.
    """

    def __init__(self, model_name: str | None = None, dim: int | None = None) -> None:
        self.model_name = model_name or settings.embed_model
        self.dim = dim or settings.embed_dim
        self._backend: Embeddings = self._build_backend()

    def _build_backend(self) -> Embeddings:
        if is_vertex_model(self.model_name):
            from langchain_google_vertexai import VertexAIEmbeddings

            if not settings.google_cloud_project:
                # 조용히 HF로 떨어지면 "왜 다른 모델이 돌지?"를 디버깅하게 되므로 명시적으로 막는다.
                raise ValueError(
                    f"Vertex 임베딩 모델({self.model_name})인데 GOOGLE_CLOUD_PROJECT가 비어 있다 "
                    "— .env에 GOOGLE_CLOUD_PROJECT + GOOGLE_APPLICATION_CREDENTIALS 설정 필요"
                )
            logger.info("임베딩 백엔드=Vertex model=%s dim=%d", self.model_name, self.dim)
            # 인증은 ADC(GOOGLE_APPLICATION_CREDENTIALS, config가 os.environ으로 bridge)로 처리된다.
            # model_name은 pydantic 필드지만 mypy가 생성자 시그니처에서 못 읽는다(런타임 정상).
            return VertexAIEmbeddings(  # type: ignore[call-arg]
                model_name=self.model_name,
                project=settings.google_cloud_project,
                location=settings.google_cloud_location,
                dimensions=self.dim,  # MRL 무손실 절단 (gemini 3072→768, 현재 스키마 유지)
            )

        from langchain_huggingface import HuggingFaceEmbeddings

        logger.info("임베딩 백엔드=HuggingFace model=%s", self.model_name)
        return HuggingFaceEmbeddings(model_name=self.model_name)

    def embed_documents(
        self, texts: list[str], task_type: EmbedTaskType = "CLUSTERING"
    ) -> list[list[float]]:
        """텍스트 배치를 임베딩한다. Vertex는 task_type을 반영, HF는 무시한다.

        Vertex AI 배치 한도(50)를 넘지 않도록 EMBED_BATCH_SIZE로 잘라 호출한다(설계 05 §2.3).
        빈 입력은 빈 리스트를 반환한다(모델 로딩은 __init__에서 이미 끝났다).
        """
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), settings.embed_batch_size):
            batch = texts[start : start + settings.embed_batch_size]
            if is_vertex_model(self.model_name):
                # embeddings_task_type은 VertexAIEmbeddings 전용 kwarg(베이스 Embeddings엔 없음).
                vectors.extend(
                    self._backend.embed_documents(batch, embeddings_task_type=task_type)  # type: ignore[call-arg]
                )
            else:
                vectors.extend(self._backend.embed_documents(batch))
        return vectors

    def embed_matrix(
        self, texts: list[str], task_type: EmbedTaskType = "CLUSTERING"
    ) -> np.ndarray:
        """임베딩을 float32 numpy 행렬로 반환 — 클러스터링·유사도 계산용(설계 05 §5)."""
        return np.array(self.embed_documents(texts, task_type), dtype=np.float32)


def embed_with(
    model_name: str, texts: list[str], task_type: EmbedTaskType = "CLUSTERING"
) -> np.ndarray:
    """설계 05 §11 하니스용 — 모델명만 받아 임베딩 행렬을 반환한다.

    비교 하니스는 모델마다 한 번씩만 부르므로 매 호출 새 백엔드를 로딩한다(인스턴스 재사용 불필요).
    프로덕션 임베더는 EmbeddingClient를 직접 만들어 단계 수명 동안 재사용한다.
    """
    return EmbeddingClient(model_name=model_name).embed_matrix(texts, task_type)
