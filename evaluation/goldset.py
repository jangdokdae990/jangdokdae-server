"""골드셋 로더 — 라벨링된 골드셋 JSON을 읽어 항목·gold 레이블을 반환한다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Goldset:
    items: list[dict]
    gold_labels: list[int]  # items와 같은 순서의 gold_cluster
    meta: dict

    def __len__(self) -> int:
        return len(self.items)


def load_goldset(path: Path) -> Goldset:
    """골드셋 JSON을 로드한다. gold_cluster 미라벨(None) 항목이 있으면 거부한다."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["items"]
    labels = [it.get("gold_cluster") for it in items]
    missing = sum(1 for lbl in labels if lbl is None)
    if missing:
        raise ValueError(
            f"골드셋 미라벨 {missing}건 — scripts/label_goldset.py로 gold_cluster를 먼저 채워라"
        )
    return Goldset(items=items, gold_labels=[int(lbl) for lbl in labels], meta=data.get("meta", {}))
