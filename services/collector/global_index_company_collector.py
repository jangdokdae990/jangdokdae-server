"""글로벌 지수 종목 유니버스 동기화 — 유럽·일본·홍콩·중국 대표 우량주 적재.

유로스톡스50·닛케이225·항셍·CSI300의 대표 종목을 큐레이션 정적 데이터로
``company_entities``에 ``is_active=True``로 적재한다. 미국(``overseas_company_collector``)과
달리 FinanceDataReader가 이 지수들의 구성종목 리스팅을 제공하지 않아, (티커·한글명·영문명·
GICS 섹터)를 직접 큐레이션한다. 목적은 온보딩 "관심 설정 → 종목"에 글로벌 시장을 노출하는
것이며, 분석 데이터(재무·공시·RAG)는 범위 밖이다(설계 docs/design/13).

- **stock_code**: yfinance 접미사 형식(``7203.T``·``0700.HK``·``600519.SS``·``MC.PA``). 아시아
  종목은 숫자 코드라 국내 6자리(``005930``)와 충돌하므로 거래소 접미사로 네임스페이스를 분리한다.
- **시장 코드**: ``CompanyEntity.market``이 곧 지수 코드(EUROSTOXX/NIKKEI/HANGSENG/CSI300).
- **격리**: ``corp_code=NULL``이라 DART 수집기(dart/financial/report)가 자동 제외한다.
- **멱등**: ``ON CONFLICT(stock_code) DO UPDATE`` — 재실행 안전. 접미사 티커라 국내 6자리 코드와
  키 충돌 없음.
"""

import logging
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.orm_models.company_entity import CompanyEntity
from app.db.orm_models.sector import Sector

logger = logging.getLogger(__name__)


class GlobalStock(NamedTuple):
    """큐레이션 글로벌 종목 1건. gics_code는 sectors.gics_code(섹터 레벨 2자리)."""

    stock_code: str  # yfinance 접미사 티커 (7203.T 등)
    name_ko: str
    name_en: str
    market: str  # EUROSTOXX / NIKKEI / HANGSENG / CSI300
    gics_code: str  # "10"~"60" — sectors 매핑 키. 미상이면 ""


# 유로스톡스50 대표 종목 (2026-06 기준 큐레이션). FDR 미지원이라 이름까지 직접 큐레이션한다.
# 접미사: .AS(암스테르담)·.DE(프랑크푸르트)·.PA(파리)·.MI(밀라노)·.MC(마드리드)·.HE(헬싱키).
_EUROSTOXX: tuple[GlobalStock, ...] = (
    GlobalStock("ASML.AS", "ASML", "ASML Holding", "EUROSTOXX", "45"),
    GlobalStock("MC.PA", "LVMH", "LVMH", "EUROSTOXX", "25"),
    GlobalStock("SAP.DE", "SAP", "SAP", "EUROSTOXX", "45"),
    GlobalStock("OR.PA", "로레알", "L'Oreal", "EUROSTOXX", "30"),
    GlobalStock("RMS.PA", "에르메스", "Hermes", "EUROSTOXX", "25"),
    GlobalStock("TTE.PA", "토탈에너지", "TotalEnergies", "EUROSTOXX", "10"),
    GlobalStock("SIE.DE", "지멘스", "Siemens", "EUROSTOXX", "20"),
    GlobalStock("AIR.PA", "에어버스", "Airbus", "EUROSTOXX", "20"),
    GlobalStock("SU.PA", "슈나이더 일렉트릭", "Schneider Electric", "EUROSTOXX", "20"),
    GlobalStock("SAN.PA", "사노피", "Sanofi", "EUROSTOXX", "35"),
    GlobalStock("ALV.DE", "알리안츠", "Allianz", "EUROSTOXX", "40"),
    GlobalStock("AI.PA", "에어 리퀴드", "Air Liquide", "EUROSTOXX", "15"),
    GlobalStock("DTE.DE", "도이치텔레콤", "Deutsche Telekom", "EUROSTOXX", "50"),
    GlobalStock("IBE.MC", "이베르드롤라", "Iberdrola", "EUROSTOXX", "55"),
    GlobalStock("ENEL.MI", "에넬", "Enel", "EUROSTOXX", "55"),
    GlobalStock("BNP.PA", "BNP 파리바", "BNP Paribas", "EUROSTOXX", "40"),
    GlobalStock("SAN.MC", "방코 산탄데르", "Banco Santander", "EUROSTOXX", "40"),
    GlobalStock("ITX.MC", "인디텍스 (자라)", "Inditex", "EUROSTOXX", "25"),
    GlobalStock("CS.PA", "악사", "AXA", "EUROSTOXX", "40"),
    GlobalStock("MUV2.DE", "뮌헨 재보험", "Munich Re", "EUROSTOXX", "40"),
    GlobalStock("EL.PA", "에실로룩소티카", "EssilorLuxottica", "EUROSTOXX", "35"),
    GlobalStock("DG.PA", "방시", "Vinci", "EUROSTOXX", "20"),
    GlobalStock("BAS.DE", "바스프", "BASF", "EUROSTOXX", "15"),
    GlobalStock("MBG.DE", "메르세데스-벤츠", "Mercedes-Benz Group", "EUROSTOXX", "25"),
    GlobalStock("BMW.DE", "BMW", "BMW", "EUROSTOXX", "25"),
    GlobalStock("VOW3.DE", "폭스바겐", "Volkswagen", "EUROSTOXX", "25"),
    GlobalStock("IFX.DE", "인피니언", "Infineon Technologies", "EUROSTOXX", "45"),
    GlobalStock("ADS.DE", "아디다스", "Adidas", "EUROSTOXX", "25"),
    GlobalStock("DHL.DE", "DHL 그룹", "DHL Group", "EUROSTOXX", "20"),
    GlobalStock("BAYN.DE", "바이엘", "Bayer", "EUROSTOXX", "35"),
    GlobalStock("DB1.DE", "도이체 뵈르제", "Deutsche Boerse", "EUROSTOXX", "40"),
    GlobalStock("ENI.MI", "ENI", "Eni", "EUROSTOXX", "10"),
    GlobalStock("ISP.MI", "인테사 산파올로", "Intesa Sanpaolo", "EUROSTOXX", "40"),
    GlobalStock("UCG.MI", "우니크레디트", "UniCredit", "EUROSTOXX", "40"),
    GlobalStock("STLAM.MI", "스텔란티스", "Stellantis", "EUROSTOXX", "25"),
    GlobalStock("BBVA.MC", "BBVA", "BBVA", "EUROSTOXX", "40"),
    GlobalStock("INGA.AS", "ING 그룹", "ING Group", "EUROSTOXX", "40"),
    GlobalStock("PRX.AS", "프로서스", "Prosus", "EUROSTOXX", "50"),
    GlobalStock("ADYEN.AS", "아디엔", "Adyen", "EUROSTOXX", "45"),
    GlobalStock("AD.AS", "아홀드 델하이즈", "Ahold Delhaize", "EUROSTOXX", "30"),
    GlobalStock("NOKIA.HE", "노키아", "Nokia", "EUROSTOXX", "45"),
    GlobalStock("KER.PA", "케링 (구찌)", "Kering", "EUROSTOXX", "25"),
    GlobalStock("SAF.PA", "사프란", "Safran", "EUROSTOXX", "20"),
    GlobalStock("BN.PA", "다논", "Danone", "EUROSTOXX", "30"),
    GlobalStock("RI.PA", "페르노 리카", "Pernod Ricard", "EUROSTOXX", "30"),
    GlobalStock("CAP.PA", "캡제미니", "Capgemini", "EUROSTOXX", "45"),
    GlobalStock("SGO.PA", "생고뱅", "Saint-Gobain", "EUROSTOXX", "15"),
    GlobalStock("DTG.DE", "다임러 트럭", "Daimler Truck", "EUROSTOXX", "20"),
    GlobalStock("MRK.DE", "머크 (독일)", "Merck KGaA", "EUROSTOXX", "35"),
    GlobalStock("NDA-FI.HE", "노르데아 은행", "Nordea Bank", "EUROSTOXX", "40"),
)

# 닛케이225 대표 종목 (도쿄증권거래소, 접미사 .T).
_NIKKEI: tuple[GlobalStock, ...] = (
    GlobalStock("7203.T", "도요타 자동차", "Toyota Motor", "NIKKEI", "25"),
    GlobalStock("6758.T", "소니 그룹", "Sony Group", "NIKKEI", "25"),
    GlobalStock("6861.T", "키엔스", "Keyence", "NIKKEI", "45"),
    GlobalStock("8035.T", "도쿄 일렉트론", "Tokyo Electron", "NIKKEI", "45"),
    GlobalStock("9984.T", "소프트뱅크 그룹", "SoftBank Group", "NIKKEI", "50"),
    GlobalStock("9983.T", "패스트리테일링 (유니클로)", "Fast Retailing", "NIKKEI", "25"),
    GlobalStock("6098.T", "리크루트 홀딩스", "Recruit Holdings", "NIKKEI", "20"),
    GlobalStock("4063.T", "신에쓰 화학", "Shin-Etsu Chemical", "NIKKEI", "15"),
    GlobalStock("8306.T", "미쓰비시 UFJ 파이낸셜", "Mitsubishi UFJ Financial", "NIKKEI", "40"),
    GlobalStock("6501.T", "히타치", "Hitachi", "NIKKEI", "20"),
    GlobalStock("7974.T", "닌텐도", "Nintendo", "NIKKEI", "50"),
    GlobalStock("6902.T", "덴소", "Denso", "NIKKEI", "25"),
    GlobalStock("6594.T", "니덱", "Nidec", "NIKKEI", "20"),
    GlobalStock("4502.T", "다케다 약품", "Takeda Pharmaceutical", "NIKKEI", "35"),
    GlobalStock("6367.T", "다이킨 공업", "Daikin Industries", "NIKKEI", "20"),
    GlobalStock("8058.T", "미쓰비시 상사", "Mitsubishi Corporation", "NIKKEI", "20"),
    GlobalStock("8001.T", "이토추 상사", "Itochu", "NIKKEI", "20"),
    GlobalStock("9433.T", "KDDI", "KDDI", "NIKKEI", "50"),
    GlobalStock("9432.T", "NTT", "Nippon Telegraph and Telephone", "NIKKEI", "50"),
    GlobalStock("7741.T", "호야", "Hoya", "NIKKEI", "35"),
    GlobalStock("6981.T", "무라타 제작소", "Murata Manufacturing", "NIKKEI", "45"),
    GlobalStock("4661.T", "오리엔탈 랜드", "Oriental Land", "NIKKEI", "25"),
    GlobalStock("7267.T", "혼다", "Honda Motor", "NIKKEI", "25"),
    GlobalStock("6954.T", "화낙", "Fanuc", "NIKKEI", "20"),
    GlobalStock("4519.T", "주가이 제약", "Chugai Pharmaceutical", "NIKKEI", "35"),
    GlobalStock("6146.T", "디스코", "Disco", "NIKKEI", "45"),
    GlobalStock("7011.T", "미쓰비시 중공업", "Mitsubishi Heavy Industries", "NIKKEI", "20"),
    GlobalStock("8766.T", "도쿄 해상 홀딩스", "Tokio Marine", "NIKKEI", "40"),
    GlobalStock("8316.T", "미쓰이스미토모 파이낸셜", "Sumitomo Mitsui Financial", "NIKKEI", "40"),
    GlobalStock("6273.T", "SMC", "SMC", "NIKKEI", "20"),
)

# 항셍지수 대표 종목 (홍콩증권거래소, 접미사 .HK).
_HANGSENG: tuple[GlobalStock, ...] = (
    GlobalStock("0700.HK", "텐센트", "Tencent Holdings", "HANGSENG", "50"),
    GlobalStock("9988.HK", "알리바바", "Alibaba Group", "HANGSENG", "25"),
    GlobalStock("0941.HK", "차이나 모바일", "China Mobile", "HANGSENG", "50"),
    GlobalStock("1299.HK", "AIA 그룹", "AIA Group", "HANGSENG", "40"),
    GlobalStock("0939.HK", "중국건설은행", "China Construction Bank", "HANGSENG", "40"),
    GlobalStock("1810.HK", "샤오미", "Xiaomi", "HANGSENG", "45"),
    GlobalStock("3690.HK", "메이퇀", "Meituan", "HANGSENG", "25"),
    GlobalStock("0388.HK", "홍콩거래소", "Hong Kong Exchanges", "HANGSENG", "40"),
    GlobalStock("1398.HK", "공상은행", "ICBC", "HANGSENG", "40"),
    GlobalStock("0005.HK", "HSBC 홀딩스", "HSBC Holdings", "HANGSENG", "40"),
    GlobalStock("2318.HK", "중국평안보험", "Ping An Insurance", "HANGSENG", "40"),
    GlobalStock("0883.HK", "중국해양석유 (CNOOC)", "CNOOC", "HANGSENG", "10"),
    GlobalStock("3988.HK", "중국은행", "Bank of China", "HANGSENG", "40"),
    GlobalStock("1024.HK", "콰이쇼우", "Kuaishou Technology", "HANGSENG", "50"),
    GlobalStock("9618.HK", "JD닷컴", "JD.com", "HANGSENG", "25"),
    GlobalStock("2020.HK", "안타 스포츠", "Anta Sports", "HANGSENG", "25"),
    GlobalStock("0386.HK", "시노펙", "Sinopec", "HANGSENG", "10"),
    GlobalStock("1211.HK", "BYD", "BYD", "HANGSENG", "25"),
    GlobalStock("0291.HK", "화룬맥주", "China Resources Beer", "HANGSENG", "30"),
    GlobalStock("2382.HK", "서니 옵티컬", "Sunny Optical", "HANGSENG", "45"),
    GlobalStock("9999.HK", "넷이즈", "NetEase", "HANGSENG", "50"),
    GlobalStock("0001.HK", "CK 허치슨", "CK Hutchison", "HANGSENG", "20"),
    GlobalStock("1928.HK", "샌즈 차이나", "Sands China", "HANGSENG", "25"),
    GlobalStock("2331.HK", "리닝", "Li Ning", "HANGSENG", "25"),
    GlobalStock("0669.HK", "테크트로닉", "Techtronic Industries", "HANGSENG", "25"),
    GlobalStock("0016.HK", "신훙지산", "Sun Hung Kai Properties", "HANGSENG", "60"),
    GlobalStock("2628.HK", "중국생명보험", "China Life Insurance", "HANGSENG", "40"),
    GlobalStock("0027.HK", "갤럭시 엔터테인먼트", "Galaxy Entertainment", "HANGSENG", "25"),
    GlobalStock("1093.HK", "CSPC 제약", "CSPC Pharmaceutical", "HANGSENG", "35"),
    GlobalStock("0992.HK", "레노버", "Lenovo Group", "HANGSENG", "45"),
)

# CSI300 대표 종목 (상하이 .SS / 선전 .SZ A주).
_CSI300: tuple[GlobalStock, ...] = (
    GlobalStock("600519.SS", "구이저우 마오타이", "Kweichow Moutai", "CSI300", "30"),
    GlobalStock("300750.SZ", "CATL (닝더스다이)", "CATL", "CSI300", "20"),
    GlobalStock("601318.SS", "중국평안보험", "Ping An Insurance", "CSI300", "40"),
    GlobalStock("600036.SS", "초상은행", "China Merchants Bank", "CSI300", "40"),
    GlobalStock("000858.SZ", "우량예", "Wuliangye Yibin", "CSI300", "30"),
    GlobalStock("002594.SZ", "BYD", "BYD", "CSI300", "25"),
    GlobalStock("600276.SS", "항서제약 (헝루이)", "Jiangsu Hengrui", "CSI300", "35"),
    GlobalStock("601899.SS", "쯔진광업", "Zijin Mining", "CSI300", "15"),
    GlobalStock("600900.SS", "창장전력", "China Yangtze Power", "CSI300", "55"),
    GlobalStock("000333.SZ", "메이디 그룹", "Midea Group", "CSI300", "25"),
    GlobalStock("601166.SS", "흥업은행", "Industrial Bank", "CSI300", "40"),
    GlobalStock("600030.SS", "중신증권", "CITIC Securities", "CSI300", "40"),
    GlobalStock("000651.SZ", "거리전기", "Gree Electric", "CSI300", "25"),
    GlobalStock("002415.SZ", "하이크비전", "Hikvision", "CSI300", "45"),
    GlobalStock("600887.SS", "이리실업", "Inner Mongolia Yili", "CSI300", "30"),
    GlobalStock("601398.SS", "공상은행", "ICBC", "CSI300", "40"),
    GlobalStock("600028.SS", "시노펙", "Sinopec", "CSI300", "10"),
    GlobalStock("601288.SS", "중국농업은행", "Agricultural Bank of China", "CSI300", "40"),
    GlobalStock("000001.SZ", "핑안은행", "Ping An Bank", "CSI300", "40"),
    GlobalStock("600000.SS", "푸둥발전은행", "SPD Bank", "CSI300", "40"),
    GlobalStock("002304.SZ", "양허주류", "Jiangsu Yanghe", "CSI300", "30"),
    GlobalStock("600309.SS", "완화화학", "Wanhua Chemical", "CSI300", "15"),
    GlobalStock("601012.SS", "롱지 그린에너지", "LONGi Green Energy", "CSI300", "45"),
    GlobalStock("300059.SZ", "동방재부", "East Money", "CSI300", "40"),
    GlobalStock("000725.SZ", "BOE 테크놀로지", "BOE Technology", "CSI300", "45"),
    GlobalStock("600438.SS", "통웨이", "Tongwei", "CSI300", "15"),
    GlobalStock("601088.SS", "중국신화에너지", "China Shenhua Energy", "CSI300", "10"),
    GlobalStock("600585.SS", "안후이 콘치 시멘트", "Anhui Conch Cement", "CSI300", "15"),
    GlobalStock("000568.SZ", "루저우 라오자오", "Luzhou Laojiao", "CSI300", "30"),
    GlobalStock("600031.SS", "싼이중공업", "Sany Heavy Industry", "CSI300", "20"),
)

# 전체 글로벌 지수 종목. 시장별 큐레이션을 한 시퀀스로 모은다.
GLOBAL_INDEX_STOCKS: tuple[GlobalStock, ...] = (
    _EUROSTOXX + _NIKKEI + _HANGSENG + _CSI300
)


def build_global_index_records(
    stocks: tuple[GlobalStock, ...],
    gics_to_sector_id: dict[str, int],
) -> list[dict[str, object]]:
    """큐레이션 종목 → CompanyEntity upsert 레코드. gics_code를 sector_id로 해소한다.

    gics_code가 비었거나 sectors에 없으면 sector_id=NULL(섹터 필터에서 제외).
    corp_code=None이라 DART 수집에서 자동 제외된다.
    """
    records: list[dict[str, object]] = []
    for stock in stocks:
        sector_id = gics_to_sector_id.get(stock.gics_code) if stock.gics_code else None
        records.append(
            {
                "stock_code": stock.stock_code,
                "name_ko": stock.name_ko,
                "name_en": stock.name_en,
                "corp_code": None,
                "market": stock.market,
                "sector_id": sector_id,
                "aliases": [],
                "is_active": True,
            }
        )
    return records


async def sync_global_index_companies(db: AsyncSession) -> dict[str, int]:
    """글로벌 지수 종목 유니버스를 company_entities에 동기화(upsert).

    Returns:
        {"total": 적재 종목 수, "EUROSTOXX"/"NIKKEI"/"HANGSENG"/"CSI300": 시장별 수}
    """
    sector_rows = (await db.execute(select(Sector.id, Sector.gics_code))).all()
    gics_to_sector_id = {gics: sid for sid, gics in sector_rows}

    records = build_global_index_records(GLOBAL_INDEX_STOCKS, gics_to_sector_id)

    BATCH = 500
    for i in range(0, len(records), BATCH):
        batch = records[i: i + BATCH]
        stmt = pg_insert(CompanyEntity).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_code"],
            set_={
                "name_ko": stmt.excluded.name_ko,
                "name_en": stmt.excluded.name_en,
                "market": stmt.excluded.market,
                "sector_id": stmt.excluded.sector_id,
                "is_active": stmt.excluded.is_active,
            },
        )
        await db.execute(stmt)
        await db.commit()

    counts: dict[str, int] = {"total": len(records)}
    for record in records:
        market = str(record["market"])
        counts[market] = counts.get(market, 0) + 1
    logger.info("글로벌 지수 적재 완료: %s", counts)
    return counts
