"""DB 조회·갱신 쿼리 모음 — 파이프라인 단계 간 DB 접근을 한곳에 모은다.

임베딩·클러스터링 단계의 상태 핸드오프 쿼리를 둔다. 각 단계는 "미처리 레코드"만 집어가므로
부분 실패 후 재실행해도 남은 것만 처리된다(멱등).
"""

from datetime import date, datetime

from sqlalchemy import (
    ColumnElement,
    Text,
    any_,
    delete,
    func,
    or_,
    select,
    type_coerce,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.db.base import KST_NOW
from app.db.orm_models.company_entity import CompanyEntity
from app.db.orm_models.issue_docent import IssueDocent
from app.db.orm_models.market import Market
from app.db.orm_models.news import News
from app.db.orm_models.news_analysis import NewsAnalysis
from app.db.orm_models.news_cluster import NewsCluster
from app.db.orm_models.report_chunk import ReportChunk
from app.db.orm_models.sector import Sector
from app.db.orm_models.stock_price import StockPrice
from app.db.orm_models.user import User
from app.db.orm_models.user_interest_company import UserInterestCompany
from app.db.orm_models.user_interest_market import UserInterestMarket
from app.db.orm_models.user_interest_sector import UserInterestSector

# 온보딩 시장 코드 → CompanyEntity.market(거래소) 매핑. 국내 거래소만 데이터 보유.
# 해외(NASDAQ/SP500/US_ETF/GLOBAL)는 매핑이 없어 종목 필터 시 빈 결과로 수렴한다.
MARKET_CODE_TO_EXCHANGES: dict[str, tuple[str, ...]] = {
    "KOSPI": ("KOSPI",),
    "KOSDAQ": ("KOSDAQ",),
}

def _escape_like(value: str) -> str:
    """LIKE 메타문자(\\,%,_)를 이스케이프 — 사용자 입력이 와일드카드로 해석되지 않게 한다.

    백슬래시를 먼저 치환해야 뒤이어 추가되는 이스케이프 백슬래시가 중복 처리되지 않는다.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def get_unembedded_news(db: AsyncSession) -> list[News]:
    """임베딩 대기 뉴스 조회 — is_filtered=FALSE AND embedding IS NULL.

    탈락분·기임베딩분은 제외돼 재실행해도 새 미임베딩분만 집어간다(멱등).
    """
    result = await db.execute(
        select(News)
        .where(News.is_filtered.is_(False))
        .where(News.embedding.is_(None))
        .order_by(News.id)
    )
    return list(result.scalars().all())


async def get_unembedded_report_chunks(db: AsyncSession) -> list[ReportChunk]:
    """임베딩 대기 사업보고서 청크 조회 — embedding IS NULL."""
    result = await db.execute(
        select(ReportChunk).where(ReportChunk.embedding.is_(None)).order_by(ReportChunk.id)
    )
    return list(result.scalars().all())


async def save_news_embeddings(db: AsyncSession, id_to_vector: dict[int, list[float]]) -> int:
    """뉴스 임베딩을 id별로 일괄 저장. 저장 건수를 반환(빈 입력은 0, DB 미접근)."""
    if not id_to_vector:
        return 0
    # SQLAlchemy 2.0 ORM 일괄 UPDATE(기본키 기준) — 행마다 UPDATE 문을 모아 1회 round-trip.
    await db.execute(
        update(News),
        [{"id": news_id, "embedding": vector} for news_id, vector in id_to_vector.items()],
    )
    await db.commit()
    return len(id_to_vector)


async def get_latest_cluster_members(db: AsyncSession) -> tuple[dict[int, set[int]], int]:
    """직전 클러스터링 상태를 cluster id 승계용으로 로드한다.

    반환: ({stable_id → 멤버 news_id 집합}, 다음 신규 stable_id).
    가장 최근 run_date의 stable_id 있는 행을 직전 클러스터로 보고, 다음 id는 전체 max+1로 둔다
    (재사용 방지). 이력이 없으면 ({}, 1).
    """
    latest = (await db.execute(select(func.max(NewsCluster.run_date)))).scalar()
    next_id = ((await db.execute(select(func.max(NewsCluster.stable_id)))).scalar() or 0) + 1
    if latest is None:
        return {}, next_id
    rows = (
        await db.execute(
            select(NewsCluster.stable_id, NewsCluster.member_news_ids)
            .where(NewsCluster.run_date == latest)
            .where(NewsCluster.stable_id.is_not(None))
        )
    ).all()
    prev = {int(sid): set(members) for sid, members in rows}
    return prev, next_id


async def save_chunk_embeddings(db: AsyncSession, id_to_vector: dict[int, list[float]]) -> int:
    """사업보고서 청크 임베딩을 id별로 일괄 저장. 저장 건수를 반환(빈 입력은 0)."""
    if not id_to_vector:
        return 0
    await db.execute(
        update(ReportChunk),
        [{"id": chunk_id, "embedding": vector} for chunk_id, vector in id_to_vector.items()],
    )
    await db.commit()
    return len(id_to_vector)


async def get_clusterable_news(db: AsyncSession, since: datetime) -> list[News]:
    """클러스터링 대상 뉴스 조회 — 당일 수집·임베딩 완료·미탈락·비중복·미분석분.

    since(KST naive)는 수집 시각 하한 — 없으면 미분석 백로그 전체가 매일 재클러스터링된다.
    근접 중복·전처리 탈락·분석 완료 행은 제외한다.
    """
    result = await db.execute(
        select(News)
        .where(News.created_at >= since)
        .where(News.is_filtered.is_(False))
        .where(News.is_duplicate.is_(False))
        .where(News.is_analyzed.is_(False))
        .where(News.embedding.is_not(None))
        .order_by(News.id)
    )
    return list(result.scalars().all())


# ── 분석 단계(NewsAnalyzer, →10) 핸드오프 ──────────────────────────────
# 분류·콘텐츠 적재는 (cluster_id) 유니크 키로 ON CONFLICT DO NOTHING — 재실행 멱등.
# 아래 save_*·mark_*는 commit하지 않는다(이슈 1건의 분류·콘텐츠·플래그를 호출부가 한 번에 commit).


async def get_unanalyzed_clusters(
    db: AsyncSession, run_date: date, limit: int
) -> list[NewsCluster]:
    """분석 대기 클러스터 — 해당 실행일자 중 아직 news_analysis가 없는 것, importance 내림차순.

    이미 분석된 클러스터(news_analysis 존재)는 제외해 재실행 시 남은 것만 처리한다(멱등).
    """
    analyzed = select(NewsAnalysis.cluster_id)
    result = await db.execute(
        select(NewsCluster)
        .where(NewsCluster.run_date == run_date)
        .where(NewsCluster.id.notin_(analyzed))
        .order_by(NewsCluster.importance.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


# ── 분석 전용 러너(scripts.run_analysis) 보조 — 날짜 무관 타겟·재실행 ──────────────
# run()의 get_unanalyzed_clusters는 "오늘(KST)" 클러스터만 보지만, 로컬 테스트는 과거 날짜
# 클러스터를 대상으로 돌려야 하므로 날짜 필터 없는 조회·특정 id 조회·재실행 삭제를 따로 둔다.


async def get_latest_unanalyzed_clusters(
    db: AsyncSession, limit: int, min_size: int = 1
) -> list[NewsCluster]:
    """미분석 클러스터를 run_date 무관하게 최신순으로 N건 — 로컬 분석 테스트용.

    run_date 필터가 없다는 점만 get_unanalyzed_clusters와 다르다(news_analysis 존재분은 제외).
    min_size 이상 크기만 대상(기본 1=전체). limit<=0이면 무제한.
    """
    analyzed = select(NewsAnalysis.cluster_id)
    stmt = (
        select(NewsCluster)
        .where(NewsCluster.id.notin_(analyzed))
        .where(NewsCluster.size >= min_size)
        .order_by(NewsCluster.run_date.desc(), NewsCluster.importance.desc())
    )
    if limit > 0:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_analyzed_clusters(
    db: AsyncSession, limit: int, min_size: int = 1
) -> list[NewsCluster]:
    """이미 분석된(news_analysis 존재) 클러스터를 최신순으로 N건 — 배치 재분석(--rerun)용.

    get_latest_unanalyzed_clusters의 역(`id IN (분석됨)`). 분류 개선 등으로 기존 적재분을 다시
    분석할 때 대상이 된다. min_size 이상만, limit<=0이면 무제한.
    """
    analyzed = select(NewsAnalysis.cluster_id)
    stmt = (
        select(NewsCluster)
        .where(NewsCluster.id.in_(analyzed))
        .where(NewsCluster.size >= min_size)
        .order_by(NewsCluster.run_date.desc(), NewsCluster.importance.desc())
    )
    if limit > 0:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_cluster_by_id(db: AsyncSession, cluster_id: int) -> NewsCluster | None:
    """특정 클러스터 1건 조회(분석 여부 무관) — 러너의 --cluster-id 타겟용. 없으면 None."""
    result = await db.execute(select(NewsCluster).where(NewsCluster.id == cluster_id))
    return result.scalars().first()


async def delete_analysis_for_cluster(
    db: AsyncSession, cluster_id: int, member_news_ids: list[int]
) -> None:
    """클러스터의 기존 분석 산출물을 지워 재분석을 허용한다(러너 --rerun).

    save_*가 ON CONFLICT DO NOTHING이라 삭제 없이는 덮어쓰기가 안 된다. news_analysis·
    issue_docent 행을 지우고 멤버 News의 is_analyzed=False로 되돌린다. 커밋은 호출부 책임.
    """
    await db.execute(delete(NewsAnalysis).where(NewsAnalysis.cluster_id == cluster_id))
    await db.execute(delete(IssueDocent).where(IssueDocent.cluster_id == cluster_id))
    if member_news_ids:
        await db.execute(
            update(News).where(News.id.in_(member_news_ids)).values(is_analyzed=False)
        )


async def get_cluster_articles(db: AsyncSession, member_news_ids: list[int]) -> list[News]:
    """클러스터 소속 기사 News 행을 member_news_ids 순서(중심 근접순)대로 반환한다."""
    if not member_news_ids:
        return []
    result = await db.execute(select(News).where(News.id.in_(member_news_ids)))
    by_id = {n.id: n for n in result.scalars().all()}
    return [by_id[i] for i in member_news_ids if i in by_id]


async def save_news_analysis(
    db: AsyncSession,
    *,
    cluster_id: int,
    scope: str,
    frame: str,
    origin: str,
    direction: str,
    confidence: float,
    sector_tags: list[str],
    company_tags: list[dict],
    company_ids: list[int],
    sector_ids: list[int],
    term_tags: list[str],
    needs_review: bool,
    is_investment_relevant: bool = True,
) -> None:
    """분류 결과를 적재(클러스터당 1행, 중복 시 무시).

    company_ids·sector_ids는 태그(이름)를 마스터(company_entities·sectors)로 해소한 백필 —
    "특정 기업/섹터를 언급한 이슈" 조회·주가 연동의 조인 키. 원문 태그는 그대로 함께 보존한다.
    is_investment_relevant=False면 비투자성 뉴스 — 분류만 남기고 issue_docent는 생략한다(호출부).
    """
    stmt = (
        pg_insert(NewsAnalysis)
        .values(
            cluster_id=cluster_id,
            scope=scope,
            frame=frame,
            origin=origin,
            direction=direction,
            confidence=confidence,
            sector_tags=sector_tags,
            company_tags=company_tags,
            company_ids=company_ids,
            sector_ids=sector_ids,
            term_tags=term_tags,
            needs_review=needs_review,
            is_investment_relevant=is_investment_relevant,
        )
        .on_conflict_do_nothing(index_elements=["cluster_id"])
    )
    await db.execute(stmt)


async def save_issue_docent(
    db: AsyncSession,
    *,
    cluster_id: int,
    title: str,
    market_ids: list[int],
    sector_ids: list[int],
    company_ids: list[int],
    hook_lines: dict,
    content_heads: list[dict],
    connection_module: list[dict],
    evidence_spans: list[dict],
    term_spans: list[dict],
) -> None:
    """생성 콘텐츠를 적재(클러스터당 1행, 중복 시 무시).

    market_ids·sector_ids·company_ids는 온보딩 관심사 기반 피드 필터의 조인 키 —
    분류 단계에서 해소된 값을 그대로 받는다(news_analysis와 동일 소스).
    """
    stmt = (
        pg_insert(IssueDocent)
        .values(
            cluster_id=cluster_id,
            title=title,
            market_ids=market_ids,
            sector_ids=sector_ids,
            company_ids=company_ids,
            hook_lines=hook_lines,
            content_heads=content_heads,
            connection_module=connection_module,
            evidence_spans=evidence_spans,
            term_spans=term_spans,
        )
        .on_conflict_do_nothing(index_elements=["cluster_id"])
    )
    await db.execute(stmt)


async def mark_news_analyzed(db: AsyncSession, news_ids: list[int]) -> None:
    """클러스터 소속 기사를 분석 완료로 표시(is_analyzed=True). 빈 입력은 무동작."""
    if not news_ids:
        return
    await db.execute(update(News).where(News.id.in_(news_ids)).values(is_analyzed=True))


# ── OPINION 현재가 보강용 key 조회 (설계 08 §5 OPINION 몫, 10 §6) ──────────
# 분류기는 기업명만 주므로 name→stock_code(company_entities)→최신 종가(stock_prices)로 잇는다.


async def get_company_by_name(db: AsyncSession, name: str) -> CompanyEntity | None:
    """기업명으로 company_entity 조회 — name_ko 정확 일치, 없으면 aliases 폴백. 미스 시 None."""
    if not name:
        return None
    result = await db.execute(
        select(CompanyEntity)
        .where((CompanyEntity.name_ko == name) | (name == any_(CompanyEntity.aliases)))
        .limit(1)
    )
    return result.scalars().first()


# ── 태그→마스터 id 해소(백필) — news_analysis.company_ids/sector_ids 적재용 ────────
# 분류기는 기업·섹터 이름만 주므로, 관계형 조회·주가 연동을 위해 마스터 id로 해소한다.
# 미매칭 이름은 결과에서 제외하고(원문 태그는 보존) 부분 매칭을 허용한다.


async def resolve_company_ids(db: AsyncSession, names: list[str]) -> list[int]:
    """기업명 목록을 company_entities.id로 해소 — name_ko 정확 일치 OR aliases 폴백.

    get_company_by_name()과 같은 매칭 규칙을 N개 이름에 대해 1쿼리로 묶는다. 매칭된 id만
    오름차순·중복 제거해 반환(미매칭 이름은 제외). 빈 입력은 빈 리스트(DB 미접근).
    """
    wanted = [n for n in {n.strip() for n in names} if n]
    if not wanted:
        return []
    # aliases는 generic ARRAY라 .overlap()이 없음 → postgresql ARRAY로 재해석해 배열 겹침(&&).
    aliases_pg = type_coerce(CompanyEntity.aliases, PG_ARRAY(Text))
    result = await db.execute(
        select(CompanyEntity.id).where(
            CompanyEntity.name_ko.in_(wanted) | aliases_pg.overlap(wanted)
        )
    )
    return sorted({row[0] for row in result.all()})


async def resolve_sector_ids(db: AsyncSession, names: list[str]) -> list[int]:
    """섹터명 목록을 sectors.id로 해소 — sectors.name_ko 정확 일치(마스터가 단일 소스).

    매칭된 id만 오름차순·중복 제거해 반환. 마스터에 없는 섹터명은 제외(원문 sector_tags는 보존).
    빈 입력은 빈 리스트(DB 미접근).
    """
    wanted = [n for n in {n.strip() for n in names} if n]
    if not wanted:
        return []
    result = await db.execute(select(Sector.id).where(Sector.name_ko.in_(wanted)))
    return sorted({row[0] for row in result.all()})


# 종목으로 market이 안 잡히는 해외 이슈의 폴백 — markets.code "GLOBAL"(기타 해외 시장).
_OVERSEAS_FALLBACK_MARKET_CODE = "GLOBAL"


async def resolve_market_ids(
    db: AsyncSession, company_ids: list[int], origin: str
) -> list[int]:
    """이슈와 연관된 markets.id를 해소 — issue_docent 관심사 매칭 백필.

    종목의 거래소(CompanyEntity.market: KOSPI/KOSDAQ)를 markets.code와 일치시켜 해소한다
    (종목 유니버스는 국내뿐이라 종목 기반은 KOSPI/KOSDAQ로 수렴). 종목으로 못 잡고 origin이
    해외면 GLOBAL(기타 해외 시장)로 폴백, 국내인데 종목이 없으면 빈 리스트(시장 전체 등).
    """
    if company_ids:
        result = await db.execute(
            select(Market.id)
            .join(CompanyEntity, CompanyEntity.market == Market.code)
            .where(CompanyEntity.id.in_(company_ids))
            .distinct()
        )
        ids = sorted({row[0] for row in result.all()})
        if ids:
            return ids
    if origin == "해외":
        result = await db.execute(
            select(Market.id).where(Market.code == _OVERSEAS_FALLBACK_MARKET_CODE)
        )
        return sorted({row[0] for row in result.all()})
    return []


async def get_latest_stock_price(db: AsyncSession, stock_code: str) -> StockPrice | None:
    """종목 코드의 최신 거래일 주가 1건. 데이터 없으면 None."""
    result = await db.execute(
        select(StockPrice)
        .where(StockPrice.stock_code == stock_code)
        .order_by(StockPrice.date.desc())
        .limit(1)
    )
    return result.scalars().first()


# --- 사용자 / 온보딩 관심 (인증·온보딩 단계) ---


def _user_update(user_id: int, **values: object):
    """User Core update 빌더 — onupdate가 안 먹는 updated_at을 항상 함께 SET한다."""
    return update(User).where(User.id == user_id).values(updated_at=KST_NOW, **values)


async def get_user_by_provider(
    db: AsyncSession, provider: str, provider_user_id: str
) -> User | None:
    """소셜 계정으로 사용자 단건 조회 — 콜백 upsert의 존재 판별용."""
    result = await db.execute(
        select(User)
        .where(User.provider == provider)
        .where(User.provider_user_id == provider_user_id)
    )
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_or_create_user(
    db: AsyncSession,
    provider: str,
    provider_user_id: str,
    email: str | None,
    nickname: str | None,
    profile_image_url: str | None,
) -> tuple[User, bool]:
    """소셜 계정으로 조회, 없으면 생성. (user, is_new) 반환 — 콜백 가입/로그인 분기용."""
    existing = await get_user_by_provider(db, provider, provider_user_id)
    if existing is not None:
        return existing, False
    try:
        created = await create_user(
            db, provider, provider_user_id, email, nickname, profile_image_url
        )
        return created, True
    except IntegrityError:
        # 동시 최초 로그인 race — 다른 요청이 먼저 INSERT해 unique 제약에 걸린 경우.
        # rollback 후 재조회하면 그 사용자가 잡힌다(둘 다 500 대신 정상 로그인).
        await db.rollback()
        existing = await get_user_by_provider(db, provider, provider_user_id)
        if existing is None:
            raise
        return existing, False


async def create_user(
    db: AsyncSession,
    provider: str,
    provider_user_id: str,
    email: str | None,
    nickname: str | None,
    profile_image_url: str | None,
) -> User:
    """신규 소셜 사용자 생성 후 영속화된 객체 반환."""
    user = User(
        provider=provider,
        provider_user_id=provider_user_id,
        email=email,
        nickname=nickname,
        profile_image_url=profile_image_url,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_last_login(db: AsyncSession, user_id: int) -> None:
    """로그인 시각 갱신 — KST_NOW는 DB 서버 시각(KST naive)을 쓴다."""
    await db.execute(_user_update(user_id, last_login_at=KST_NOW))
    await db.commit()


async def replace_user_interests(
    db: AsyncSession,
    user_id: int,
    market_ids: list[int],
    sector_ids: list[int],
    company_ids: list[int],
) -> None:
    """관심을 전량 교체하고 온보딩 완료 시각을 갱신한다(재진입 멱등).

    기존 관심을 모두 지우고 새로 삽입 → 부분 갱신·diff 없이 제출분이 곧 최종 상태가 된다.
    세 삭제·삽입·플래그 갱신을 한 트랜잭션으로 커밋한다.
    """
    await db.execute(delete(UserInterestMarket).where(UserInterestMarket.user_id == user_id))
    await db.execute(delete(UserInterestSector).where(UserInterestSector.user_id == user_id))
    await db.execute(delete(UserInterestCompany).where(UserInterestCompany.user_id == user_id))

    # dict.fromkeys — 중복 id가 들어와도 unique 제약 위반 없이 1행씩만 삽입(입력 순서 보존).
    db.add_all(
        [UserInterestMarket(user_id=user_id, market_id=mid) for mid in dict.fromkeys(market_ids)]
    )
    db.add_all(
        [UserInterestSector(user_id=user_id, sector_id=sid) for sid in dict.fromkeys(sector_ids)]
    )
    db.add_all(
        [UserInterestCompany(user_id=user_id, company_id=cid) for cid in dict.fromkeys(company_ids)]
    )

    await db.execute(_user_update(user_id, onboarding_completed_at=KST_NOW))
    await db.commit()


async def get_user_interests(db: AsyncSession, user_id: int) -> dict[str, list[int]]:
    """사용자 관심 대상 id를 종류별로 반환 — /auth/me·프로필 응답용."""
    market_rows = await db.execute(
        select(UserInterestMarket.market_id).where(UserInterestMarket.user_id == user_id)
    )
    sector_rows = await db.execute(
        select(UserInterestSector.sector_id).where(UserInterestSector.user_id == user_id)
    )
    company_rows = await db.execute(
        select(UserInterestCompany.company_id).where(UserInterestCompany.user_id == user_id)
    )
    return {
        "market_ids": list(market_rows.scalars().all()),
        "sector_ids": list(sector_rows.scalars().all()),
        "company_ids": list(company_rows.scalars().all()),
    }


# --- 마스터 조회 (온보딩 1~3단계, guest 허용) ---


async def get_active_markets(db: AsyncSession) -> list[Market]:
    result = await db.execute(
        select(Market).where(Market.is_active.is_(True)).order_by(Market.id)
    )
    return list(result.scalars().all())


async def get_all_sectors(db: AsyncSession) -> list[Sector]:
    result = await db.execute(select(Sector).order_by(Sector.name_ko))
    return list(result.scalars().all())


async def search_companies(
    db: AsyncSession,
    sector_id: int | None,
    market_code: str | None,
    q: str | None,
    limit: int,
    cursor: int | None,
) -> list[CompanyEntity]:
    """활성 종목을 필터·검색·커서 페이지네이션으로 조회.

    market_code는 markets.code(거래소·지수)이고 CompanyEntity.market(KOSPI/KOSDAQ)과 동일
    값이라 그대로 비교한다. 종목 유니버스가 국내뿐이라 해외 코드(NASDAQ 등)는 빈 결과로 수렴한다.
    cursor는 직전 페이지 마지막 id로, id 오름차순에서 그 다음부터 limit개를 가져온다.
    """
    stmt = select(CompanyEntity).where(CompanyEntity.is_active.is_(True))
    if sector_id is not None:
        stmt = stmt.where(CompanyEntity.sector_id == sector_id)
    if market_code is not None:
        stmt = stmt.where(CompanyEntity.market == market_code)
    if q:
        escaped = _escape_like(q)
        stmt = stmt.where(
            or_(
                CompanyEntity.name_ko.ilike(f"%{escaped}%", escape="\\"),
                CompanyEntity.stock_code.ilike(f"{escaped}%", escape="\\"),
            )
        )
    if cursor is not None:
        stmt = stmt.where(CompanyEntity.id > cursor)
    stmt = stmt.order_by(CompanyEntity.id).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# --- 관심 대상 유효성 검증 (온보딩 제출 시) ---


async def _filter_existing_ids(
    db: AsyncSession,
    id_column: InstrumentedAttribute[int],
    ids: list[int],
    *conditions: ColumnElement[bool],
) -> set[int]:
    """주어진 id 중 (조건을 만족하며) 실제 존재하는 것만 집합으로 반환. 빈 입력은 DB를 안 친다."""
    if not ids:
        return set()
    result = await db.execute(select(id_column).where(id_column.in_(ids), *conditions))
    return set(result.scalars().all())


async def get_active_market_ids(db: AsyncSession, ids: list[int]) -> set[int]:
    return await _filter_existing_ids(db, Market.id, ids, Market.is_active.is_(True))


async def get_existing_sector_ids(db: AsyncSession, ids: list[int]) -> set[int]:
    return await _filter_existing_ids(db, Sector.id, ids)


async def get_active_company_ids(db: AsyncSession, ids: list[int]) -> set[int]:
    return await _filter_existing_ids(
        db, CompanyEntity.id, ids, CompanyEntity.is_active.is_(True)
    )
