"""임베딩 클러스터링 시각화 + 품질 검증 — 실제 뉴스로 결과를 눈으로·지표로 확인한다.

클러스터링 결과를 시각화해 "같은 이슈가 실제로 한 덩어리로 뭉치는가"를 검증한다.

산출물(output/, gitignore):
    - cluster_<model>.html  : plotly 인터랙티브 — 점에 마우스 올리면 제목+클러스터
    - cluster_<model>.png   : matplotlib 정적 스캐터(한글 폰트)
    - cluster_<model>.md    : 클러스터별 제목 목록
    + 콘솔: 자동 지표 + (min_cluster_size, min_samples) 그리드 스윕

주의:
    클러스터링은 원차원(768/1024) 공간에서 하고, t-SNE는 보기용 2D 투영일 뿐이다. 2D에서
    가까워/멀어 보이는 건 투영 왜곡일 수 있으니, 색(클러스터 라벨)과 hover(제목)로 판단한다.

사용:
    python -m scripts.embedding_cluster_visualize [n_titles] [model]
    # 기본: 400건, gemini-embedding-001 (gemini는 .env GOOGLE_APPLICATION_CREDENTIALS 필요)
"""

import asyncio
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")  # GUI 없이 파일로만 저장 — pyplot import 전에 백엔드 지정
import matplotlib.pyplot as plt  # noqa: E402
import plotly.express as px  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from sklearn.manifold import TSNE  # noqa: E402

from scripts.embedding_compare_unsupervised import fetch_titles  # noqa: E402
from services.embedder.cluster import (  # noqa: E402
    DEFAULT_MIN_CLUSTER_SIZE,
    DEFAULT_MIN_SAMPLES,
    cluster_news,
    evaluate_clustering,
)
from services.embedder.embedding_client import embed_with  # noqa: E402

DEFAULT_N_TITLES = 400
DEFAULT_MODEL = "gemini-embedding-001"
_KOREAN_FONT = "/System/Library/Fonts/Supplemental/AppleGothic.ttf"

# t-SNE 축은 고차원 임베딩을 2D로 압축한 좌표라 축 값·방향 자체엔 의미가 없다(거리·이웃만 의미).
_AXIS_X = "t-SNE 1 (축 값 자체는 의미 없음 · 점 사이 거리만 해석)"
_AXIS_Y = "t-SNE 2 (축 값 자체는 의미 없음 · 점 사이 거리만 해석)"
_CAPTION = (
    "t-SNE: 고차원 임베딩을 2D로 압축한 그림. 축 값·방향엔 의미가 없고, 점이 가까울수록 "
    "임베딩이 유사(같은 이슈 가능성↑)합니다. 색 = 클러스터, 회색 = noise(단독 기사)."
)
_CAPTION_HTML = _CAPTION + " 점에 마우스를 올리면 기사 제목이 표시됩니다."


def _setup_korean_font() -> None:
    """matplotlib에 한글 폰트를 등록한다 — 없으면 제목이 □□로 깨진다(macOS 기준)."""
    if Path(_KOREAN_FONT).exists():
        font_manager.fontManager.addfont(_KOREAN_FONT)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=_KOREAN_FONT).get_name()
    plt.rcParams["axes.unicode_minus"] = False  # 마이너스 기호 깨짐 방지


# import 시 1회 등록 — 이 모듈을 import하는 모든 스크립트(실험 드라이버 포함)에 폰트 적용
_setup_korean_font()


def project_2d(embeddings: np.ndarray) -> np.ndarray:
    """원차원 임베딩을 t-SNE로 2D 투영한다(보기용). cosine 거리·PCA 초기화."""
    n = len(embeddings)
    perplexity = min(30, max(5, n // 4))  # 표본이 적으면 perplexity를 낮춰야 t-SNE가 동작
    tsne = TSNE(
        n_components=2, metric="cosine", init="pca", perplexity=perplexity, random_state=42
    )
    return tsne.fit_transform(embeddings)


def quality_report(embeddings: np.ndarray, labels: np.ndarray) -> None:
    """자동 지표 + 정성 체크리스트를 콘솔에 출력한다."""
    m = evaluate_clustering(embeddings, labels)
    sil = f"{m['silhouette']:.3f}" if m["silhouette"] is not None else "n/a"
    db = f"{m['davies_bouldin']:.3f}" if m["davies_bouldin"] is not None else "n/a"
    print("=== 자동 품질 지표 (설계 §5.5) ===")
    print(f"  클러스터 수 : {m['n_clusters']}")
    print(f"  noise 비율  : {m['noise_ratio']:.1%}   (50% 넘으면 min_cluster_size 낮춰야)")
    print(f"  silhouette  : {sil}   (높을수록 좋음, 금융 뉴스는 0.2~0.35도 정상)")
    print(f"  Davies-Bouldin: {db}   (낮을수록 좋음)")
    print("\n  정성 체크(HTML/MD로 직접 확인): 같은 날 같은 이슈 기사가 한 클러스터인가? "
          "서로 다른 이슈가 섞이지 않았나? 20건 초과 거대 클러스터는 없나?")


def param_sweep(embeddings: np.ndarray) -> None:
    """(min_cluster_size, min_samples) 2D 그리드 스윕 — 파라미터 적정성 검증."""
    mcs_grid = [2, 3, 4, 5]
    ms_grid: list[int | None] = [1, 2, 3, None]  # None = HDBSCAN 기본(=min_cluster_size)
    print("\n=== 파라미터 그리드 스윕 (설계 §5.6) — 현재 기본값 mcs=2, ms=1 ===")
    print(f"  {'mcs':>4} {'ms':>5} {'clusters':>9} {'silhouette':>11} {'noise':>7}")
    for mcs in mcs_grid:
        for ms in ms_grid:
            labels = cluster_news(embeddings, min_cluster_size=mcs, min_samples=ms or mcs)
            m = evaluate_clustering(embeddings, labels)
            sil = f"{m['silhouette']:.3f}" if m["silhouette"] is not None else "  n/a"
            noise = f"{m['noise_ratio']:.1%}"
            print(f"  {mcs:>4} {str(ms):>5} {m['n_clusters']:>9} {sil:>11} {noise:>7}")


def _group_clusters(titles: list[str], labels: np.ndarray) -> dict[int, list[str]]:
    clusters: dict[int, list[str]] = {}
    for title, label in zip(titles, labels.tolist()):
        clusters.setdefault(label, []).append(title)
    return clusters


def save_plotly_html(
    coords: np.ndarray, labels: np.ndarray, titles: list[str], path: Path, model_name: str
) -> None:
    """인터랙티브 스캐터 — 점에 마우스 올리면 제목+클러스터. 정성 검증의 핵심 도구."""
    label_str = ["noise" if v == -1 else f"C{v}" for v in labels.tolist()]
    fig = px.scatter(
        x=coords[:, 0], y=coords[:, 1], color=label_str, hover_name=titles,
        title=f"뉴스 임베딩 클러스터링 (t-SNE 2D) — {model_name}",
        labels={"x": _AXIS_X, "y": _AXIS_Y, "color": "cluster"},
    )
    fig.update_traces(marker={"size": 8})
    # 축 눈금값은 의미가 없으므로 숨기고, 하단에 축·색 의미 캡션을 단다.
    fig.update_xaxes(showticklabels=False)
    fig.update_yaxes(showticklabels=False)
    # 클러스터가 많아 범례는 끄고 hover로 본다. 하단 여백(margin b)은 캡션 공간.
    fig.update_layout(showlegend=False, margin={"b": 110})
    fig.add_annotation(
        text=_CAPTION_HTML, xref="paper", yref="paper", x=0, y=-0.13,
        showarrow=False, align="left", font={"size": 12},
    )
    fig.write_html(str(path))


def save_matplotlib_png(
    coords: np.ndarray, labels: np.ndarray, path: Path, model_name: str
) -> None:
    """정적 스캐터(PNG) — noise는 회색, 클러스터는 tab20 색상."""
    fig, ax = plt.subplots(figsize=(12, 9))
    noise = labels == -1
    ax.scatter(coords[noise, 0], coords[noise, 1], c="lightgrey", s=12, alpha=0.5, label="noise")
    clustered = ~noise
    ax.scatter(
        coords[clustered, 0], coords[clustered, 1],
        c=labels[clustered], cmap="tab20", s=18,
    )
    ax.set_title(f"뉴스 임베딩 클러스터링 (t-SNE 2D) — {model_name}")
    ax.set_xlabel(_AXIS_X)
    ax.set_ylabel(_AXIS_Y)
    ax.set_xticks([])  # 축 눈금값은 의미 없음 — 숨긴다
    ax.set_yticks([])
    # 하단 캡션 — 축·색·거리의 의미 설명
    fig.text(0.5, 0.005, _CAPTION, ha="center", va="bottom", fontsize=10, wrap=True)
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def save_cluster_members_md(
    titles: list[str], labels: np.ndarray, path: Path, model_name: str
) -> None:
    """클러스터별 제목 목록 — 큰 클러스터부터 나열한다."""
    clusters = _group_clusters(titles, labels)
    lines = [f"# 클러스터 멤버 — {model_name}\n"]
    real = {k: v for k, v in clusters.items() if k != -1}
    for label, members in sorted(real.items(), key=lambda kv: len(kv[1]), reverse=True):
        lines.append(f"## 클러스터 {label} ({len(members)}건)")
        lines.extend(f"- {t}" for t in members)
        lines.append("")
    noise = clusters.get(-1, [])
    lines.append(f"## noise / 단독 ({len(noise)}건)")
    lines.extend(f"- {t}" for t in noise)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(n_titles: int, model_name: str) -> None:
    titles = asyncio.run(fetch_titles(n_titles))
    print(f"제목 {len(titles)}건 · 모델 {model_name}\n")
    if len(titles) < 2:
        print("제목이 너무 적어 클러스터링 불가.")
        return

    embeddings = embed_with(model_name, titles, task_type="CLUSTERING")
    labels = cluster_news(
        embeddings, min_cluster_size=DEFAULT_MIN_CLUSTER_SIZE, min_samples=DEFAULT_MIN_SAMPLES
    )

    quality_report(embeddings, labels)
    param_sweep(embeddings)

    _setup_korean_font()
    coords = project_2d(embeddings)
    outdir = Path("output")
    outdir.mkdir(exist_ok=True)
    slug = model_name.replace("/", "_")
    html_path = outdir / f"cluster_{slug}.html"
    png_path = outdir / f"cluster_{slug}.png"
    md_path = outdir / f"cluster_{slug}.md"
    save_plotly_html(coords, labels, titles, html_path, model_name)
    save_matplotlib_png(coords, labels, png_path, model_name)
    save_cluster_members_md(titles, labels, md_path, model_name)

    print("\n=== 산출물 ===")
    print(f"  인터랙티브: {html_path}  (브라우저로 열어 hover로 제목 확인)")
    print(f"  정적 이미지: {png_path}")
    print(f"  클러스터 목록: {md_path}")


if __name__ == "__main__":
    arg_n = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_N_TITLES
    arg_model = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODEL
    main(arg_n, arg_model)
