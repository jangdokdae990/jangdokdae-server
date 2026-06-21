# 단독 실행: uv run pytest tests/test_eval_metrics.py -s
"""evaluation.metrics 단위 테스트 — 쌍별 F1·ARI·NMI (설계 01 §4 / bake-off 01).

손계산 가능한 소형 라벨로 쌍별 정밀도·재현율·F1을 검증한다.
"""

import math

from evaluation.metrics import pairwise_prf, score


def test_perfect_match_is_f1_one():
    true = [0, 0, 1, 1, 2]
    assert pairwise_prf(true, list(true)) == (1.0, 1.0, 1.0)


def test_all_singletons_pred_gives_zero_recall():
    # gold엔 같은 쌍이 있는데 예측이 전부 단독이면 TP=0 → recall·F1=0.
    true = [0, 0, 0]
    pred = [0, 1, 2]
    precision, recall, f1 = pairwise_prf(true, pred)
    assert recall == 0.0
    assert f1 == 0.0


def test_handcomputed_partial_overlap():
    # gold same-pairs={(0,1),(0,2),(1,2),(3,4)}=4, pred same-pairs={(0,1),(2,3),(2,4),(3,4)}=4,
    # 교집합 TP={(0,1),(3,4)}=2 → P=2/4, R=2/4, F1=0.5.
    true = [0, 0, 0, 1, 1]
    pred = [0, 0, 1, 1, 1]
    precision, recall, f1 = pairwise_prf(true, pred)
    assert math.isclose(precision, 0.5)
    assert math.isclose(recall, 0.5)
    assert math.isclose(f1, 0.5)


def test_score_bundles_ari_nmi():
    true = [0, 0, 1, 1]
    sc = score(true, list(true))
    assert sc.pair_f1 == 1.0
    assert math.isclose(sc.ari, 1.0)
    assert math.isclose(sc.nmi, 1.0)
