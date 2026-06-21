"""클러스터링 평가 지표 — 쌍별 F1(주지표) + ARI·NMI(보조).

쌍별 F1: 모든 기사 쌍을 "같은 클러스터인가"로 보고, gold 대비 예측의 정밀도·재현율을 낸다.
같은 이슈 묶기(우리 과제)에 가장 직접적이라 주지표로 쓴다(설계 01 §4).
"""

from __future__ import annotations

from dataclasses import dataclass

from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
from sklearn.metrics.cluster import pair_confusion_matrix


@dataclass(frozen=True)
class ClusterScores:
    pair_precision: float
    pair_recall: float
    pair_f1: float
    ari: float
    nmi: float


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def pairwise_prf(labels_true: list[int], labels_pred: list[int]) -> tuple[float, float, float]:
    """쌍별 (precision, recall, F1)를 반환한다.

    pair_confusion_matrix는 [[TN, FP], [FN, TP]] 쌍 카운트를 준다(상수배는 비율에 무영향).
    precision=TP/(TP+FP)=같다고 본 쌍 중 실제 같은 비율, recall=TP/(TP+FN)=실제 같은 쌍 중 맞춘 비율.
    """  # noqa: E501 — 설명 주석(지표 정의)
    (_, fp), (fn, tp) = pair_confusion_matrix(labels_true, labels_pred)
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return precision, recall, f1


def score(labels_true: list[int], labels_pred: list[int]) -> ClusterScores:
    """주지표(쌍별 F1) + 보조지표(ARI·NMI)를 한 번에 계산한다."""
    precision, recall, f1 = pairwise_prf(labels_true, labels_pred)
    return ClusterScores(
        pair_precision=precision,
        pair_recall=recall,
        pair_f1=f1,
        ari=float(adjusted_rand_score(labels_true, labels_pred)),
        nmi=float(normalized_mutual_info_score(labels_true, labels_pred)),
    )
