"""DB 조회·갱신 쿼리 모음 — 파이프라인 단계 간 DB 접근을 한곳에 모은다.

임베딩·클러스터링 단계의 상태 핸드오프 쿼리를 둔다. 각 단계는 "미처리 레코드"만 집어가므로
부분 실패 후 재실행해도 남은 것만 처리된다(멱등).
"""

from datetime import datetime

from sqlalchemy import ColumnElement, delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.db.base import KST_NOW
from app.db.orm_models.company_entity import CompanyEntity
from app.db.orm_models.market import Market
from app.db.orm_models.news import News
from app.db.orm_models.report_chunk import ReportChunk
from app.db.orm_models.sector import Sector
from app.db.orm_models.user import User
from app.db.orm_models.user_interest_company import UserInterestCompany
from app.db.orm_models.user_interest_market import UserInterestMarket
from app.db.orm_models.user_interest_sector import UserInterestSector

# 온보딩 시장 코드 → CompanyEntity.market(거래소) 매핑. 국내만 데이터 보유.
MARKET_CODE_TO_EXCHANGES: dict[str, tuple[str, ...]] = {"KR": ("KOSPI", "KOSDAQ")}


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

    market_code(국내=KR)는 거래소(KOSPI/KOSDAQ)로 풀어 필터한다. cursor는 직전 페이지
    마지막 id로, id 오름차순에서 그 다음부터 limit개를 가져온다.
    """
    stmt = select(CompanyEntity).where(CompanyEntity.is_active.is_(True))
    if sector_id is not None:
        stmt = stmt.where(CompanyEntity.sector_id == sector_id)
    if market_code is not None:
        exchanges = MARKET_CODE_TO_EXCHANGES.get(market_code, ())
        # 매핑 없는 시장(해외 등)은 보유 데이터가 없어 빈 결과로 수렴시킨다.
        stmt = stmt.where(CompanyEntity.market.in_(exchanges))
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
