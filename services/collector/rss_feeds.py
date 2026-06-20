"""RSS 피드 레지스트리 로더 — YAML 정본(config/news_feeds.yaml)을 읽어 FeedSource로 노출.

피드 목록의 정본은 코드 상수가 아니라 YAML 설정 파일이다(설계 02 §4) — 피드 추가·비활성화를
코드 배포 없이 운영 중 처리하기 위함. 이 모듈은 YAML을 FeedSource 리스트로 로드하고
active=false 피드를 제외한 ALL_FEEDS를 노출한다(공개 API는 종전과 동일).
"""

from dataclasses import dataclass
from pathlib import Path

from utils.config_loader import read_config_yaml

# 레지스트리 정본 — 루트 config/news_feeds.yaml. 이 파일 기준 상대 경로로 찾는다.
FEEDS_YAML = Path(__file__).resolve().parents[2] / "config" / "news_feeds.yaml"


@dataclass(frozen=True)
class FeedSource:
    """수집 대상 RSS 피드 1개의 메타데이터."""

    url: str          # 실제 요청 보낼 RSS 주소
    rss_source: str   # 피드 식별자. 예: "hankyung_finance"
    # 기사에 <source>가 없을 때 news_source 폴백으로 쓰는 언론사명. 예: "한국경제"
    publisher: str
    # 권역(korea/us/global, 선택) — 분류·필터용 메타. 미지정 시 korea.
    region: str = "korea"
    # 오프셋 없는 발행시각을 해석할 기준 타임존. 국내 섹션 피드는 모두 KST(기본).
    # 예: einfomax는 "2026-06-17 10:40:00"처럼 오프셋 없이 KST를 주므로 UTC로 보면 9h 밀린다.
    tz: str = "Asia/Seoul"


def load_feeds(path: Path = FEEDS_YAML, *, active_only: bool = True) -> list[FeedSource]:
    """YAML 레지스트리에서 피드를 로드한다. active_only면 active=false 피드를 제외한다.

    필수 키(rss_source/publisher/url)가 없으면 KeyError로 즉시 실패한다 — 잘못된 레지스트리를
    조용히 건너뛰면 수집량 급감을 놓친다. region/tz/active는 기본값을 적용한다.
    """
    raw = read_config_yaml(path)
    feeds: list[FeedSource] = []
    for entry in raw.get("feeds", []):
        if active_only and not entry.get("active", True):
            continue
        feeds.append(
            FeedSource(
                url=entry["url"],
                rss_source=entry["rss_source"],
                publisher=entry["publisher"],
                region=entry.get("region", "korea"),
                tz=entry.get("tz", "Asia/Seoul"),
            )
        )
    return feeds


# 모듈 임포트 시 1회 로드 — 활성 피드만. (공개 API: rss_collector가 ALL_FEEDS를 임포트)
ALL_FEEDS: list[FeedSource] = load_feeds()
