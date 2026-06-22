"""테이블별 UPSERT 공통 도구 — 수집기·에이전트가 공유하는 DB 저장 경계.

각 수집기의 to_record() 산출물(list[dict])을 받아 PostgreSQL ON CONFLICT로 멱등
저장한다. 테이블별 충돌 키는 upsert_* 함수가 캡슐화한다. 대량 입력은 바인드 파라미터
상한을 넘지 않게 청크로 나눠 실행하되 전체를 1회 commit해 원자성을 유지한다.
"""

from collections.abc import Iterator

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.orm_models.disclosure import Disclosure
from app.db.orm_models.financial_statement import FinancialStatement
from app.db.orm_models.market_indicator import MarketIndicator
from app.db.orm_models.news import News
from app.db.orm_models.news_cluster import NewsCluster
from app.db.orm_models.report_chunk import ReportChunk
from app.db.orm_models.stock_price import StockPrice

# PostgreSQL 바인드 파라미터 상한(65,535) 회피용 안전 마진.
# 1회 멀티로우 INSERT의 파라미터 수 = 행 수 × 컬럼 수 → 컬럼 수로 나눠 청크 크기를 정한다.
_MAX_BIND_PARAMS = 30000


def _chunks(
    records: list[dict], n_cols: int | None = None, max_params: int | None = None
) -> Iterator[list[dict]]:
    """records를 INSERT 파라미터 한계(행×컬럼) 이하 청크로 분할.

    n_cols는 INSERT에 실제 바인딩되는 컬럼 수다. client-side default 컬럼도 바인딩되므로
    레코드 키 수로 추정하면 과소평가돼 한계를 넘는다 — 미지정 시 레코드 키 합집합으로 추정.
    max_params는 테스트에서 작은 한계값을 주입하기 위한 시드(seam)다.
    """
    limit = _MAX_BIND_PARAMS if max_params is None else max_params
    cols = n_cols if n_cols is not None else (len({k for r in records for k in r}) or 1)
    chunk_size = max(1, limit // cols)
    for start in range(0, len(records), chunk_size):
        yield records[start : start + chunk_size]


async def _upsert(
    db: AsyncSession,
    model: type[Base],
    records: list[dict],
    index_elements: list[str],
    update_columns: list[str] | None = None,
) -> int:
    """records를 UPSERT하고 반영(삽입+갱신) 건수를 반환. 빈 입력은 0.

    충돌 시 기본은 무시(DO NOTHING). update_columns를 주면 해당 컬럼만 갱신(DO UPDATE)한다.
    대량 입력은 청크로 나눠 실행하되 전체를 1회 commit해 원자성을 유지한다.
    """
    if not records:
        return 0
    # client-side default 컬럼까지 바인딩될 수 있으므로 모델 전체 컬럼 수를 상한으로 잡는다
    n_cols = len(model.__table__.columns)
    affected = 0
    for chunk in _chunks(records, n_cols=n_cols):
        stmt = pg_insert(model).values(chunk)
        if update_columns:
            stmt = stmt.on_conflict_do_update(
                index_elements=index_elements,
                set_={col: stmt.excluded[col] for col in update_columns},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=index_elements)
        result = await db.execute(stmt)
        affected += result.rowcount  # type: ignore[attr-defined]
    await db.commit()
    return affected


async def upsert_news(db: AsyncSession, records: list[dict]) -> int:
    """뉴스 레코드를 guid 기준 UPSERT. records는 CollectedNews.to_record() 형식.

    guid가 수집-시점 정확 중복키다(피드 GUID, 없으면 정규화 URL — 전처리에서 폴백). url은
    unique가 아니라(일반 인덱스) 충돌키로 못 쓴다. DO NOTHING은 배치 내 동일 guid도 멱등 처리.
    """
    return await _upsert(db, News, records, ["guid"])


async def upsert_stock_prices(db: AsyncSession, records: list[dict]) -> int:
    """주가 레코드를 (stock_code, date) 기준 UPSERT. records는 CollectedPrice.to_record() 형식."""
    return await _upsert(db, StockPrice, records, ["stock_code", "date"])


async def upsert_disclosures(db: AsyncSession, records: list[dict]) -> int:
    """공시 레코드를 rcept_no 기준 UPSERT. records는 CollectedDisclosure.to_record() 형식."""
    return await _upsert(db, Disclosure, records, ["rcept_no"])


async def upsert_market_indicators(db: AsyncSession, records: list[dict]) -> int:
    """거시지표를 (indicator_type, currency, date) 기준 UPSERT — 충돌 시 value 갱신.

    ECOS는 잠정치를 이후 확정치로 개정할 수 있으므로 같은 (지표·통화·일자)를 재수집하면
    value를 새 값으로 갱신한다(DO NOTHING이면 잠정치가 영구 고정됨).
    """
    return await _upsert(
        db,
        MarketIndicator,
        records,
        ["indicator_type", "currency", "date"],
        update_columns=["value"],
    )


async def upsert_financial_statements(db: AsyncSession, records: list[dict]) -> int:
    """재무제표를 (corp_code, year, quarter) 기준 UPSERT."""
    return await _upsert(db, FinancialStatement, records, ["corp_code", "year", "quarter"])


async def upsert_report_chunks(db: AsyncSession, records: list[dict]) -> int:
    """사업보고서 청크를 (corp_code, report_year, chunk_type, subsection) 기준 UPSERT."""
    keys = ["corp_code", "report_year", "chunk_type", "subsection"]
    return await _upsert(db, ReportChunk, records, keys)


async def upsert_news_clusters(db: AsyncSession, records: list[dict]) -> int:
    """클러스터를 (run_date, representative_news_id) 기준 UPSERT — 충돌 시 내용 갱신.

    같은 날 재실행 시 같은 대표 기사의 클러스터가 새 기사로 커질 수 있으므로
    소속·크기·중요도를 새 값으로 갱신한다. 같은 입력 재실행은 멱등하다.
    """
    return await _upsert(
        db,
        NewsCluster,
        records,
        ["run_date", "representative_news_id"],
        update_columns=["member_news_ids", "size", "importance", "stable_id"],
    )
