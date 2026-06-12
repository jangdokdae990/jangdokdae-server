# 뉴스 데이터 수집 기획서

> **작성자** Kim minkyoung · **작성일** 2026-05-28 (2026-06-12 핵심 압축 개정)
>
> **범위** 뉴스 수집 → 저장 (전처리는 [04](./04-preprocessing-design.md), 임베딩은 [05](./05-embedding-clustering-design.md))
>
> **핵심 결정**: 16개 고정 RSS 피드에서 **제목+URL만** 수집(저작권). 키워드 검색 없음. 본문은 분석 시점 대표기사만 실시간 fetch 후 폐기. 종목 식별은 분석 단계(06) NER 담당.

---

## 목차

- [1. 개요](#1-개요)
- [2. 수집 대상 정의](#2-수집-대상-정의)
- [3. 저작권 및 법적 검토](#3-저작권-및-법적-검토)
- [4. 수집 소스 검토](#4-수집-소스-검토)
- [5. 수집 방법](#5-수집-방법)
- [6. 주요 뉴스 선정 — 클러스터링 단계 담당](#6-주요-뉴스-선정--클러스터링-단계-담당)
- [7. 뉴스 수집 단계](#7-뉴스-수집-단계)
- [8. 데이터 명세](#8-데이터-명세)
- [9. 수집 주기](#9-수집-주기)
- [10. 시스템 아키텍처](#10-시스템-아키텍처)
- [11. 구현 로드맵](#11-구현-로드맵)
- [12. 미결 사항](#12-미결-사항)

---

## 1. 개요

뉴스는 장독대의 가장 중요한 원재료다 — 주린이용 풀이 생성·오늘의 주요 이슈·관심 종목 피드·Issue Docent 전부의 입력.

**수집 목표**: 국내 증권 + 해외 글로벌 경제를 고정 RSS만으로(API 키 불필요), 제목+URL+메타데이터만 저장.

**일별 수집량 추정**: 국내 13피드 ~650건 + investing.com 3피드 ~30건 = **~680건/일** (중복 제거 후 ~310건). 실측(2026-06-11): 1회 폴링 552건 → 전처리 통과 391건.

---

## 2. 수집 대상 정의

16개 고정 피드에서 들어오는 **증권·경제 뉴스 전체** — 시장/종목/산업 구분 없이 섞여 들어오고, **수집 시점에 분류하지 않는다**(고정 RSS엔 라벨이 없음). 유형 분류·종목 식별(`company_tags`)은 분석 단계(06) NER 담당.

| 항목 | 내용 |
|------|------|
| 범위 결정 | **피드 선택**으로 결정 (키워드·종목 쿼리 없음) |
| 국내 / 해외 | 증권 전문 RSS 13개 / investing.com 3개 (외환·해외주식·경제지표) |
| 수집 안 함 | 본문·snippet·이미지 (저작권 → [3장](#3-저작권-및-법적-검토)) |

---

## 3. 저작권 및 법적 검토

**채택 전략: 제목+URL만 저장, snippet·본문은 DB 저장 금지.** 본문이 필요하면(분석 시점) 대표 기사만 실시간 fetch 후 즉시 폐기.

근거 — 수집 방법별 리스크:

| 행위 | 리스크 |
|------|--------|
| 공개 RSS에서 제목·URL 수집·저장 | **낮음** — 언론사가 공개 배포한 메타데이터 |
| 분석 시점 본문 fetch 후 즉시 폐기 | **낮음** — 저장 없음, 내부 처리 목적 |
| 뉴스 본문 전체 DB 저장 | **높음** — 저작물 무단 복제 |
| robots.txt 위반 직접 크롤링 | **높음** — 업무방해 소지 (대법원 2021도1533 기준) |

장독대는 투자 추천이 아닌 **학습 서비스**라 약관 해석에 유리하나, 유료화·광고 수익화 시 재검토가 필요하다.

---

## 4. 수집 소스 검토

**채택**: 국내 증권 전문 RSS 13개 + investing.com RSS 3개 (모두 API 키 불필요).
**제외**: Google News RSS(증권 특화로 대체), Finnhub·Naver API(키 의존성), BigKinds(유료 전환).

피드 URL 목록의 **정본은 코드**([`services/collector/rss_feeds.py`](../../services/collector/rss_feeds.py)) — 한국경제·매일경제·연합인포맥스·이데일리·서울경제 등 국내 13 + investing.com 외환/주식/경제지표 3. 피드 추가·제거는 상수 목록만 수정.

---

## 5. 수집 방법

모든 소스가 RSS이므로 `feedparser` + `httpx.AsyncClient`로 통일 — `Semaphore(5)` 동시 요청 제한, User-Agent 지정, 16피드 병렬 폴링 후 평탄화. 구현: [`services/collector/rss_collector.py`](../../services/collector/rss_collector.py).

수집 필드: `title` · `url` · `source` · `published`(KST naive 정규화 — 국내 피드는 KST, investing.com은 UTC, 오프셋 없으면 UTC로 가정해 9시간 어긋남 방지).

---

## 6. 주요 뉴스 선정 — 클러스터링 단계 담당

"오늘 주목할 뉴스" 선정은 **클러스터(기사 그룹) 단위 평가**라 임베딩·클러스터링 후에야 가능하다 → 수집 단계는 수집·저장만 하고, 클러스터링·복합 중요도·상위 이슈 선정은 EmbeddingClusterer가 담당한다. 벤치마크·신호·가중치의 단일 출처는 [05 §6](./05-embedding-clustering-design.md#6-주요-이슈-선정--복합-중요도-스코어).

---

## 7. 뉴스 수집 단계

`NewsCollector`는 메인 DAG가 09:00·15:30에 실행하는 **수집 전용** 컴포넌트 — `collect → preprocess(인메모리) → save` 정적 순차, 분기·반복·LLM 추론 없음 → Airflow Task(→ [00 §5.2](./00-workflow-airflow.md#52-뉴스-수집-정적-순차--airflow-task로-교정)). 구현: [`services/pipeline/news_collector.py`](../../services/pipeline/news_collector.py).

```
collect (RSS 16피드 폴링·KST 정규화, 실패 피드 식별)
  → run_preprocessing (HTML·URL·24h·제목중복 — 인메모리, →04)
  → upsert_news (정제본 1회 저장, ON CONFLICT(url) DO NOTHING)
```

> **State는 데이터가 아니라 보고다.** 반환값(XCom)엔 카운트와 실패 신호(`collected`/`kept`/`saved`/`failed_feeds`)만 담는다 — 실제 데이터 핸드오프는 공유 DB 상태 컬럼으로(→ [01 §2](./01-pipeline-orchestration-design.md#2-전체-구조--데이터-핸드오프)). `failed_feeds`는 일부 피드의 조용한 실패를 구조적 신호로 끌어올려 수집량 급감을 인지하게 한다.

---

## 8. 데이터 명세

### 8.1 수집·저장 필드 정의

`news` 필드를 **채워지는 시점**으로 구분한다. 전체 스키마 정본은 ORM [`app/db/orm_models/news.py`](../../app/db/orm_models/news.py).

| 필드 | 채우는 시점 | 설명 |
|------|------------|------|
| `title` / `url`(unique) | 수집→전처리 | HTML 정제·트래킹 파라미터 제거 후 저장 |
| `rss_source` / `news_source` | 수집 | 피드 식별자 / 언론사 |
| `published_at` (nullable) | 수집 | 발행 시각 KST naive (피드에 없으면 NULL) |
| `created_at` | 저장 | DB 적재 시각 (server_default, KST naive) |
| `is_filtered` | 전처리 | true = 24h 초과·제목 중복 → 분석 제외 |
| `is_duplicate` | 임베딩(중복) | true = cosine ≥ 0.95 근접 중복 soft flag (→ [05 §4.2](./05-embedding-clustering-design.md#42-중복-제거-cosine--095--하드-삭제가-아니라-soft-flag)) |
| `embedding` Vector(768) | 임베딩 | title 임베딩 |
| `is_analyzed` | 분석 | 분석 처리 여부 |

**별도 테이블로 분리**: 클러스터·스코어는 기사 그룹당 값이라 `news_cluster`로(grain 불일치 방지), 유형·종목은 분석 산출물이라 `news_analysis`(06)로.
**저장하지 않는 것**: snippet·본문·이미지·기자명 (저작권).

### 8.2 DB 스키마 (SQLAlchemy)

정본은 ORM [`app/db/orm_models/news.py`](../../app/db/orm_models/news.py). 필수 인덱스:

| 인덱스 | 용도 |
|------|------|
| `url` unique | 중복 방지 (멱등 저장 키) |
| `ix_news_unanalyzed` (partial) | 미분석분 최신순 조회 |
| `ix_news_embedding` (HNSW, cosine) | 클러스터링·유사도 검색 — **벡터 쌓이기 전 미리 생성** |
| `ix_news_created_at` | "당일 수집분" 창 조회 (dedup·클러스터링) |

### 8.3 `news_cluster` 테이블 (클러스터링 산출물)

**클러스터당 1행** — `news`(기사당)와 grain이 다르다. `run_date` · `representative_news_id`(= member[0]) · `member_news_ids`(중심 근접순 정렬) · `size` · `importance`. `(run_date, representative_news_id)` 유니크로 재실행 멱등. 정본: ORM [`news_cluster.py`](../../app/db/orm_models/news_cluster.py), 스코어 산식: [05 §6](./05-embedding-clustering-design.md#6-주요-이슈-선정--복합-중요도-스코어).

### 8.4 본문 fetch 전략

분석 시점에 대표 기사 URL만 **trafilatura**로 실시간 fetch 후 폐기(`follow_redirects` 필수 — 국내 다수 매체 http→https 301, 실측 성공률 92%).

| 상황 | 대응 |
|------|------|
| 정상 fetch | 대표기사(`member_news_ids[0]`) 본문 사용 후 폐기 |
| 페이월·실패 | 중심 근접순 다음 후보 순차 시도 |
| 전부 실패 | title만으로 분석 (품질 저하 허용) |

---

## 9. 수집 주기

한국 장 운영시간(09:00~15:20) 기준 하루 2회 — **09:00**(야간+프리마켓, 장 시작 전 이슈) / **15:30**(당일 장중 전체 + 분석 트리거). 스케줄은 Airflow DAG 담당(→ [00 §7](./00-workflow-airflow.md#7-dag-구성)).

---

## 10. 시스템 아키텍처

수집·임베딩·분석을 독립 단계로 분리하고 Airflow DAG가 조율한다. 전체 흐름·디렉토리는 [01](./01-pipeline-orchestration-design.md), DAG·스케줄은 [00](./00-workflow-airflow.md)이 단일 출처.

```
NewsCollector(수집→전처리) ─┐
                            ├→ 공유 DB (정제본) → EmbeddingClusterer → analyze (L2 → 06)
CompanyCollector           ─┘
```

---

## 11. 구현 로드맵

| Phase | 내용 | 상태 |
|:---:|------|:---:|
| 1 | RSSCollector + 도구(save_tool 등) + News 스키마 | ✅ |
| 2 | NewsCollector 조립 (collect→preprocess→save) + pgvector | ✅ |
| 3 | 전처리 모듈 (인메모리, →04) | ✅ |
| 4 | 러너 ✅ + Airflow DAG ⬜ | 진행 중 |
| 5 | 본문 fetch 품질 검증 | 1차 실측 ✅ (92%, 리다이렉트 수정 완료) — 페이월 비율은 통합테스트 때 |

---

## 12. 미결 사항

| 항목 | 내용 | 상태 |
|------|------|------|
| 임베딩 모델 | `gemini-embedding-001`(768) — 3축 평가 전 축 1위 | ✅ 확정 (2026-06-09) |
| 본문 fetch 품질 | 리다이렉트 추적 시 92% 성공(실험2), 프로덕션 fetcher 수정 완료 | ✅ 1차 검증 (2026-06-11) |
| 클러스터링 임계값 | 실뉴스 교정 테스트 | ⬜ 데이터 누적 후 |
| 관심 종목 없는 초기 사용자 | 기본 피드만 제공할지 | ⬜ 기획 논의 |

---

## 참고 자료

- [Neon pgvector 공식 문서](https://neon.com/docs/extensions/pgvector)
- [디지털 뉴스콘텐츠 이용규칙 (한국언론진흥재단)](https://www.kpf.or.kr/front/board/boardContentsView.do?board_id=291&contents_id=855b0c963b5c4a42ba6b26d06c7186d4)
- [웹크롤링 법적 판단 기준 — 대법원 2021도1533](https://atlaw.kr/kr-blog/%EC%9B%B9%ED%81%AC%EB%A1%A4%EB%A7%81%EC%9D%98-%ED%98%95%EC%82%AC%EC%B2%98%EB%B2%8C-%EA%B0%80%EB%8A%A5%EC%84%B1-%EB%8C%80%EB%B2%95%EC%9B%90-2021%EB%8F%841533-%ED%8C%90%EA%B2%B0-%EC%99%84%EC%A0%84/)
