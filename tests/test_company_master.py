# 단독 실행: uv run pytest tests/test_company_master.py -s
"""company_master_collector 섹터 매핑 회귀 테스트.

KRX 업종명 → GICS 섹터 코드 매핑이 (1) 유효한 GICS 섹터 코드만 가리키고,
(2) PyKRX가 실제로 주는 KRX 업종을 빠짐없이 덮는지 고정한다 — 미매핑 업종이 생기면
해당 종목들이 sector_id 미분류로 새기 때문.
"""

from services.collector.company_master_collector import KRX_SECTOR_TO_GICS

# sectors.gics_code (섹터 레벨 2자리) 전체
VALID_GICS = {"10", "15", "20", "25", "30", "35", "40", "45", "50", "55", "60"}

# PyKRX get_market_sector_classifications가 실제로 반환한 KRX 업종명(2026-06-17 실측 29종)
OBSERVED_KRX_SECTORS = {
    "전기·전자", "IT 서비스", "화학", "기계·장비", "제약", "일반서비스", "유통",
    "운송장비·부품", "금속", "금융", "의료·정밀기기", "기타금융", "음식료·담배",
    "오락·문화", "건설", "섬유·의류", "비금속", "운송·창고", "증권", "종이·목재",
    "부동산", "기타제조", "보험", "통신", "전기·가스", "은행", "농업 임업 및 어업",
    "전기·가스·수도", "출판·매체복제",
}


def test_all_targets_are_valid_gics_sector_codes():
    assert set(KRX_SECTOR_TO_GICS.values()) <= VALID_GICS


def test_covers_observed_krx_sectors():
    missing = OBSERVED_KRX_SECTORS - set(KRX_SECTOR_TO_GICS)
    assert not missing, f"미매핑 KRX 업종: {missing}"


def test_representative_mappings():
    assert KRX_SECTOR_TO_GICS["전기·전자"] == "45"   # IT
    assert KRX_SECTOR_TO_GICS["화학"] == "15"         # 소재
    assert KRX_SECTOR_TO_GICS["제약"] == "35"         # 헬스케어
    assert KRX_SECTOR_TO_GICS["은행"] == "40"         # 금융
    assert KRX_SECTOR_TO_GICS["통신"] == "50"         # 커뮤니케이션서비스
