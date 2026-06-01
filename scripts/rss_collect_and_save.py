"""16개 RSS 피드를 수집해 Neon DB의 news 테이블에 저장하는 데모 스크립트.

실행 방법:
  uv run python scripts/rss_collect_and_save.py

사전 조건:
  - .env에 DATABASE_URL(Neon) 설정
  - alembic upgrade head 로 news 테이블 생성 완료

url 중복은 무시되므로 여러 번 실행해도 안전하다(이미 저장된 기사는 건너뜀).
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import AsyncSessionLocal  # noqa: E402
from services.collector.rss_collector import RSSCollector  # noqa: E402
from services.collector.tools.save_tool import upsert_news  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")


async def main() -> None:
    news_list = await RSSCollector().collect()
    print(f"수집: {len(news_list)}건")

    records = [news.to_record() for news in news_list]
    async with AsyncSessionLocal() as db:
        inserted = await upsert_news(db, records)

    print(f"신규 저장: {inserted}건  (중복 무시: {len(records) - inserted}건)")


if __name__ == "__main__":
    asyncio.run(main())
