"""임베딩 클라이언트 — 모델명으로 백엔드를 분기하는 단일 임베딩 경계.

`EMBED_MODEL` 값만 바꾸면 백엔드가 자동 전환되도록 분기 규칙을 한 곳에 모은다.

분기 규칙:
    - "gemini"로 시작 → Vertex AI(관리형). gemini-embedding-001은 MRL로 EMBED_DIM 차원으로
      무손실 절단(3072→768). project/location 설정이 있어야 호출된다.
    - 그 외 → HuggingFace 로컬 로딩.

task type은 Vertex 전용 신호다. HuggingFace 백엔드는 무시한다.
"""

import logging
import time
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
# gemini-embedding-2 계열은 langchain-google-genai로 호출한다. preview라 us-central1에만
# 배포되므로 location 미지정 시 us-central1로 라우팅한다.
_GENAI_V2_PREFIX = "gemini-embedding-2"
_GENAI_V2_LOCATION = "us-central1"
# v2 preview는 콘텐츠 1건씩만 받고 분당 할당량이 낮다 → 한 건씩 보내며
# RESOURCE_EXHAUSTED(429)는 지수 백오프로 재시도한다(2·4·8·16초).
_GENAI_V2_MAX_RETRIES = 5
_GENAI_V2_BACKOFF_SEC = 2.0
# v2는 task_type을 무시하므로 task instruction을 프롬프트 앞에 붙여 용도를 구분한다.
_GENAI_V2_INSTRUCTION: dict[str, str] = {
    "RETRIEVAL_QUERY": "task: search result | query: ",
    "RETRIEVAL_DOCUMENT": "title: none | text: ",
    "CLUSTERING": "task: clustering | query: ",
    "SEMANTIC_SIMILARITY": "task: sentence similarity | query: ",
}


def is_genai_v2_model(model_name: str) -> bool:
    """gemini-embedding-2 계열(genai 백엔드, task_type 미사용·output_dimensionality 절단) 여부."""
    return model_name.startswith(_GENAI_V2_PREFIX)


def is_vertex_model(model_name: str) -> bool:
    """구 Vertex(VertexAIEmbeddings) 분기 여부 — gemini 계열이되 v2는 제외(v2는 genai 백엔드)."""
    return model_name.startswith(_GEMINI_PREFIX) and not is_genai_v2_model(model_name)


class EmbeddingClient:
    """모델명으로 백엔드를 고른 임베딩 클라이언트. 한 모델당 한 인스턴스를 재사용한다.

    모델 로딩이 무거우므로 인스턴스를 단계 수명 동안 보관한다. dim은 Vertex(MRL) 절단에만
    쓰이고, HuggingFace 모델은 네이티브 차원을 그대로 쓰므로 무시된다.
    """

    def __init__(
        self,
        model_name: str | None = None,
        dim: int | None = None,
        hf_model_kwargs: dict | None = None,
        location: str | None = None,
    ) -> None:
        self.model_name = model_name or settings.embed_model
        self.dim = dim or settings.embed_dim
        # HuggingFace 백엔드 전용 추가 인자(예: trust_remote_code). 기본값은 None.
        self.hf_model_kwargs = hf_model_kwargs
        # Vertex/genai 리전 override. 미지정 시 v2는 us-central1, 그 외는 설정값.
        self.location = location
        self._backend: Embeddings = self._build_backend()

    def _build_backend(self) -> Embeddings:
        if is_genai_v2_model(self.model_name):
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            if not settings.google_cloud_project:
                raise ValueError(
                    f"genai 임베딩 모델({self.model_name})인데 GOOGLE_CLOUD_PROJECT가 비어 있다 "
                    "— .env에 GOOGLE_CLOUD_PROJECT + GOOGLE_APPLICATION_CREDENTIALS 설정 필요"
                )
            loc = self.location or _GENAI_V2_LOCATION
            logger.info("임베딩 백엔드=genai(v2) model=%s dim=%d location=%s",
                        self.model_name, self.dim, loc)
            # output_dimensionality(MRL 절단)·task_type은 embed_documents 호출마다 전달한다.
            return GoogleGenerativeAIEmbeddings(
                model=self.model_name,
                vertexai=True,
                project=settings.google_cloud_project,
                location=loc,
            )

        if is_vertex_model(self.model_name):
            from langchain_google_vertexai import VertexAIEmbeddings

            if not settings.google_cloud_project:
                # 조용히 HF로 떨어지지 않도록 명시적으로 막는다.
                raise ValueError(
                    f"Vertex 임베딩 모델({self.model_name})인데 GOOGLE_CLOUD_PROJECT가 비어 있다 "
                    "— .env에 GOOGLE_CLOUD_PROJECT + GOOGLE_APPLICATION_CREDENTIALS 설정 필요"
                )
            logger.info("임베딩 백엔드=Vertex model=%s dim=%d", self.model_name, self.dim)
            # 인증은 ADC로 처리된다.
            # model_name은 pydantic 필드지만 mypy가 생성자 시그니처에서 못 읽는다(런타임 정상).
            return VertexAIEmbeddings(  # type: ignore[call-arg]
                model_name=self.model_name,
                project=settings.google_cloud_project,
                location=self.location or settings.google_cloud_location,
                dimensions=self.dim,  # MRL 무손실 절단 (gemini 3072→768)
            )

        from langchain_huggingface import HuggingFaceEmbeddings

        logger.info("임베딩 백엔드=HuggingFace model=%s", self.model_name)
        if self.hf_model_kwargs:
            return HuggingFaceEmbeddings(
                model_name=self.model_name, model_kwargs=self.hf_model_kwargs
            )
        return HuggingFaceEmbeddings(model_name=self.model_name)

    def embed_documents(
        self, texts: list[str], task_type: EmbedTaskType = "CLUSTERING"
    ) -> list[list[float]]:
        """텍스트 배치를 임베딩한다. Vertex/genai는 task_type을 반영, HF는 무시한다.

        Vertex AI 배치 한도를 넘지 않도록 EMBED_BATCH_SIZE로 잘라 호출한다. 빈 입력은 빈 리스트.
        """
        if not texts:
            return []
        if is_genai_v2_model(self.model_name):
            return self._embed_genai_v2(texts, task_type)
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

    def _embed_genai_v2(
        self, texts: list[str], task_type: EmbedTaskType
    ) -> list[list[float]]:
        """v2는 콘텐츠 1건씩만 받으므로 한 건씩 보내고, 429는 지수 백오프로 재시도한다.

        task_type을 무시하므로 instruction을 프롬프트 앞에 붙여 용도를 구분한다.
        """
        instruction = _GENAI_V2_INSTRUCTION.get(task_type, "")
        out: list[list[float]] = []
        for text in texts:
            prompt = f"{instruction}{text}"
            for attempt in range(_GENAI_V2_MAX_RETRIES):
                try:
                    vec = self._backend.embed_documents(  # type: ignore[call-arg]
                        [prompt],
                        batch_size=1,
                        output_dimensionality=self.dim,
                    )[0]
                    out.append(vec)
                    break
                except Exception as e:  # noqa: BLE001 — 429만 재시도, 그 외는 즉시 전파
                    is_quota = "RESOURCE_EXHAUSTED" in str(e)
                    if not is_quota or attempt == _GENAI_V2_MAX_RETRIES - 1:
                        raise
                    time.sleep(_GENAI_V2_BACKOFF_SEC * (2**attempt))
        return out

    def embed_matrix(
        self, texts: list[str], task_type: EmbedTaskType = "CLUSTERING"
    ) -> np.ndarray:
        """임베딩을 float32 numpy 행렬로 반환 — 클러스터링·유사도 계산용."""
        return np.array(self.embed_documents(texts, task_type), dtype=np.float32)


class LazyClientMixin:
    """클라이언트를 lazy 보유하는 임베더 공통 베이스 — 첫 접근에서 생성한다.

    백엔드 구축이 무거우므로 임베딩할 행이 실제로 있을 때만 만든다. 공유가 필요하면 호출부가
    만든 인스턴스를 주입한다. 사용처: NewsEmbedder·ReportEmbedder.
    """

    def __init__(self, client: EmbeddingClient | None = None) -> None:
        self._client = client

    @property
    def client(self) -> EmbeddingClient:
        if self._client is None:
            self._client = EmbeddingClient()
        return self._client


def embed_with(
    model_name: str, texts: list[str], task_type: EmbedTaskType = "CLUSTERING"
) -> np.ndarray:
    """모델명만 받아 임베딩 행렬을 반환한다 — 비교 하니스용(매 호출 새 백엔드 로딩)."""
    return EmbeddingClient(model_name=model_name).embed_matrix(texts, task_type)
