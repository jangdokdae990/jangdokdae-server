"""16개 RSS 피드에서 실제 뉴스를 수집해 결과를 출력하는 데모 스크립트.

실행 방법 (둘 중 아무거나):
  1) 터미널:  uv run python scripts/rss_collect_demo.py
  2) VSCode:  이 파일을 열고 우측 상단 ▶(Run Python File) 클릭
             — 단, 인터프리터를 프로젝트의 .venv 로 먼저 선택해야 함
             (Cmd+Shift+P → "Python: Select Interpreter" → .venv/bin/python)

DB에 저장하지 않고 수집 결과만 화면에 보여준다.
"""

import asyncio
import logging
import sys
from collections import Counter
from pathlib import Path

# 이 스크립트를 scripts/ 안에서 실행해도 프로젝트 루트의 services 패키지를 import 할 수 있게 함
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.collector.rss_collector import RSSCollector  # noqa: E402

# 피드 수집 실패·파싱 경고를 화면에서 볼 수 있도록 WARNING 레벨 로깅
logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")


async def main() -> None:
    news_list = await RSSCollector().collect()

    print(f"\n총 수집 건수: {len(news_list)}건\n")

    per_feed = Counter(news.rss_source for news in news_list)
    print("=== 피드별 수집 건수 ===")
    for rss_source, count in sorted(per_feed.items(), key=lambda item: -item[1]):
        print(f"  {rss_source:28s} {count:3d}건")

    print("\n=== 샘플 5건 ===")
    for news in news_list[:5]:
        published = news.published_at.isoformat() if news.published_at else "N/A"
        print(f"  [{news.news_source}] {news.title[:50]}")
        print(f"     rss_source={news.rss_source}  published_at={published}")


if __name__ == "__main__":
    asyncio.run(main())
