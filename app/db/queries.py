"""DB 조회·갱신 쿼리 모음 — 파이프라인 단계 간 DB 접근을 한곳에 모은다.

뉴스 전처리는 수집→전처리→1회 저장(인메모리)으로 전환돼 더는 DB 핸드오프
(preprocessed_at IS NULL 조회 → UPDATE)를 쓰지 않는다. 그에 따른 조회/갱신 함수는
제거됐다. 임베딩·분석 단계의 상태 조회(is_filtered=FALSE AND embedding IS NULL 등)는
해당 단계 구현 시 이 모듈에 추가한다.
"""
