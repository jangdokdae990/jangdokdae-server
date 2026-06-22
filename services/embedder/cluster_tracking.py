"""클러스터 id 승계 — 윈도우 재클러스터링 시 멤버 겹침으로 안정 id를 이어준다.

14일 윈도우를 매번 전체 재계산하면 같은 이슈라도 클러스터 PK가 매 실행 바뀐다. 그러면 노출된
이슈 id가 흔들려 추적·중복 노출 문제가 생긴다. 직전 실행의 클러스터(안정 id→멤버 집합)와
새 클러스터(멤버 집합)를 멤버 겹침으로 매칭해 안정 id를 승계한다.

승계 규칙(설계 05 §5.1a):
  - 매칭: 새 클러스터마다 멤버 겹침이 가장 큰 직전 클러스터를 후보로(겹침 0이면 신규 id).
  - 분할(prev 1개 → new 여러개): 겹침이 가장 큰 new가 원 id를 승계, 나머지는 신규 id.
  - 병합(prev 여러개 → new 1개): 승계받은 id 중 **가장 오래된(작은) id**를 유지.
"""

from __future__ import annotations

from collections import defaultdict


def assign_stable_ids(
    new_clusters: list[set[int]],
    prev_clusters: dict[int, set[int]],
    next_id: int,
) -> tuple[list[int], int]:
    """새 클러스터별 안정 id를 배정한다.

    new_clusters: 새 실행의 클러스터별 멤버 news_id 집합 리스트.
    prev_clusters: 직전 실행의 {안정 id → 멤버 집합}.
    next_id: 신규 클러스터에 부여할 다음 id(증가시키며 사용).
    반환: (new_clusters와 같은 순서의 안정 id 리스트, 갱신된 next_id).
    """
    # 1) 각 new 클러스터의 최적 prev 후보 — 겹침 최대(동률이면 오래된=작은 id).
    best_prev: dict[int, tuple[int, int]] = {}  # new_idx -> (prev_id, overlap)
    for i, members in enumerate(new_clusters):
        for prev_id, prev_members in prev_clusters.items():
            overlap = len(members & prev_members)
            if overlap == 0:
                continue
            cur = best_prev.get(i)
            if cur is None or overlap > cur[1] or (overlap == cur[1] and prev_id < cur[0]):
                best_prev[i] = (prev_id, overlap)

    # 2) prev id별 승자 = 그 id와 겹침이 가장 큰 new(분할 시 다수 멤버 쪽이 원 id 승계).
    winner: dict[int, tuple[int, int]] = {}  # prev_id -> (new_idx, overlap)
    for new_idx, (prev_id, overlap) in best_prev.items():
        cur = winner.get(prev_id)
        if cur is None or overlap > cur[1] or (overlap == cur[1] and new_idx < cur[0]):
            winner[prev_id] = (new_idx, overlap)

    # 3) 한 new가 여러 prev id를 승계하면(병합) 가장 오래된(작은) id 유지.
    won: dict[int, list[int]] = defaultdict(list)
    for prev_id, (new_idx, _ov) in winner.items():
        won[new_idx].append(prev_id)
    assigned: dict[int, int] = {idx: min(pids) for idx, pids in won.items()}

    # 4) 승계 못 받은 new는 신규 id.
    ids: list[int] = []
    for i in range(len(new_clusters)):
        if i in assigned:
            ids.append(assigned[i])
        else:
            ids.append(next_id)
            next_id += 1
    return ids, next_id
