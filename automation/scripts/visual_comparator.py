#!/usr/bin/env python3
"""
visual_comparator.py — Quality metrics for TikZ cover replication.

Compares an original reference image against a compiled result PNG using
three complementary metrics:

  1. SSIM (global)      — structural similarity across the whole image [0,1]
  2. Color Distance     — mean RGB distance between K-means palettes
  3. Region Match Rate  — fraction of color regions reproduced correctly [0,1]

Also writes a pixel-level diff map PNG for visual inspection.

Public API:
    compare(original_path, result_path, analysis=None, output_dir=None) -> dict

Returned dict keys:
    ssim_global       float  — overall SSIM
    ssim_pass         bool   — ssim_global >= ssim_threshold
    color_dist_mean   float  — mean palette RGB distance (lower = better)
    region_match_rate float  — fraction of regions with correct color
    region_scores     list   — per-region detail dicts
    diff_map_path     str    — path to the saved diff map PNG
    patch_hints       list   — regions that failed, formatted for Patch Engine
"""

import math
from pathlib import Path

_OUTPUT_DIR    = Path(__file__).resolve().parent.parent / "output"
_SSIM_THRESH   = 0.82   # minimum acceptable SSIM
_COLOR_MATCH   = 40.0   # max RGB distance to count a region color as "reproduced"
_N_PALETTE     = 8      # K-means clusters for palette comparison


# ─── Public API ───────────────────────────────────────────────────────────────

def compare(
    original_path: "str | Path",
    result_path:   "str | Path",
    analysis:      "dict | None" = None,
    output_dir:    "str | Path | None" = None,
    ssim_threshold: float = _SSIM_THRESH,
) -> dict:
    """
    Compare original reference image against compiled result PNG.

    Parameters
    ----------
    original_path  : original cover image (PNG/JPEG)
    result_path    : compiled cover PNG (from LuaLaTeX → pdftoppm or similar)
    analysis       : cover_analysis dict (from cover_assembler); optional.
                     When given, enables per-region scoring.
    output_dir     : where to save the diff map. Default: automation/output/
    ssim_threshold : SSIM below this triggers patch hints. Default: 0.82

    Returns
    -------
    dict with quality metrics and patch hints.
    """
    try:
        return _run_compare(
            Path(original_path).resolve(),
            Path(result_path).resolve(),
            analysis,
            Path(output_dir).resolve() if output_dir else _OUTPUT_DIR,
            ssim_threshold,
        )
    except Exception as exc:
        _s = str(exc)
        if "No module named" in _s:
            return _unavailable_result(str(exc))
        raise


# ─── Core comparison ──────────────────────────────────────────────────────────

def _run_compare(
    orig_path: Path,
    result_path: Path,
    analysis: "dict | None",
    out_dir: Path,
    thresh: float,
) -> dict:
    import numpy as np
    from PIL import Image
    from skimage.metrics import structural_similarity as ssim

    if not orig_path.exists():
        raise FileNotFoundError(f"Imagem original nao encontrada: {orig_path}")
    if not result_path.exists():
        raise FileNotFoundError(f"Resultado compilado nao encontrado: {result_path}")

    # Load and align both images to the same pixel dimensions
    orig   = np.array(Image.open(orig_path).convert("RGB"))
    result = np.array(
        Image.open(result_path).convert("RGB").resize(
            (orig.shape[1], orig.shape[0]), Image.LANCZOS
        )
    )

    # ── 1. SSIM ────────────────────────────────────────────────────────────
    ssim_val = float(ssim(orig, result, channel_axis=2, data_range=255))

    # ── 2. Color Distance ─────────────────────────────────────────────────
    palette_orig   = _extract_palette(orig,   _N_PALETTE)
    palette_result = _extract_palette(result, _N_PALETTE)
    color_dist     = _palette_distance(palette_orig, palette_result)

    # ── 3. Region Match Rate ──────────────────────────────────────────────
    regions       = (analysis or {}).get("regions", [])
    canvas        = (analysis or {}).get("canvas", {})
    W             = canvas.get("width_cm",  21.0)
    H             = canvas.get("height_cm", 29.7)
    region_scores = _score_regions(orig, result, regions, W, H, orig.shape)
    match_rate    = (
        sum(1 for s in region_scores if s["match"]) / len(region_scores)
        if region_scores else 1.0
    )

    # ── 4. Diff map ───────────────────────────────────────────────────────
    out_dir.mkdir(parents=True, exist_ok=True)
    diff_path = out_dir / "diff_map.png"
    _write_diff_map(orig, result, diff_path)

    # ── 5. Patch hints (failed regions) ──────────────────────────────────
    patch_hints = _build_patch_hints(region_scores)

    return {
        "ssim_global":       round(ssim_val, 4),
        "ssim_pass":         ssim_val >= thresh,
        "ssim_threshold":    thresh,
        "color_dist_mean":   round(color_dist, 2),
        "region_match_rate": round(match_rate, 3),
        "region_scores":     region_scores,
        "diff_map_path":     str(diff_path),
        "patch_hints":       patch_hints,
    }


# ─── Palette extraction & comparison ─────────────────────────────────────────

def _extract_palette(arr: "np.ndarray", n: int) -> "np.ndarray":
    """K-means palette of n colors from image array. Returns (n, 3) float array."""
    from sklearn.cluster import KMeans
    import numpy as np

    # Downsample for speed (300×450 thumbnail equivalent)
    h, w = arr.shape[:2]
    step = max(1, min(h, w) // 300)
    pixels = arr[::step, ::step].reshape(-1, 3).astype(float)

    km = KMeans(n_clusters=min(n, len(pixels)), n_init=5, random_state=0)
    km.fit(pixels)
    return km.cluster_centers_


def _palette_distance(p1: "np.ndarray", p2: "np.ndarray") -> float:
    """
    Mean minimum RGB distance between two palettes.
    For each color in p1, find the nearest in p2; average those distances.
    """
    import numpy as np

    total = 0.0
    for c in p1:
        dists = np.linalg.norm(p2 - c, axis=1)
        total += float(dists.min())
    return total / len(p1)


# ─── Region scoring ───────────────────────────────────────────────────────────

def _score_regions(
    orig:    "np.ndarray",
    result:  "np.ndarray",
    regions: list,
    W_cm:    float,
    H_cm:    float,
    shape:   tuple,
) -> list:
    """
    For each region bbox, crop both images and compare dominant colors.
    Returns list of {region_idx, color_hex, expected_rgb, actual_rgb, dist, match}.
    """
    import numpy as np

    h_px, w_px = shape[:2]
    scores = []

    for i, reg in enumerate(regions):
        b     = reg.get("bbox_cm", {})
        x_cm  = b.get("x", 0)
        y_cm  = b.get("y", 0)
        w_cm  = b.get("w", 0)
        h_cm  = b.get("h", 0)

        # Convert cm → pixels (TikZ: y=0 at bottom; image: y=0 at top)
        x1 = int(x_cm / W_cm * w_px)
        x2 = int((x_cm + w_cm) / W_cm * w_px)
        y1 = int((H_cm - y_cm - h_cm) / H_cm * h_px)
        y2 = int((H_cm - y_cm) / H_cm * h_px)

        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w_px, x2), min(h_px, y2)

        if x2 <= x1 or y2 <= y1:
            continue

        # Dominant color of this bbox in each image
        expected_rgb = _dominant_color(orig[y1:y2, x1:x2])
        actual_rgb   = _dominant_color(result[y1:y2, x1:x2])
        dist         = float(np.linalg.norm(
            np.array(expected_rgb) - np.array(actual_rgb)
        ))
        match        = dist <= _COLOR_MATCH

        scores.append({
            "region_idx":   i,
            "color_hex":    reg.get("color_hex", ""),
            "expected_rgb": list(expected_rgb),
            "actual_rgb":   list(actual_rgb),
            "dist":         round(dist, 1),
            "match":        match,
        })

    return scores


def _dominant_color(roi: "np.ndarray") -> "tuple[int,int,int]":
    """Return the most common color in a small ROI via 1-cluster K-means."""
    from sklearn.cluster import KMeans
    import numpy as np

    pixels = roi.reshape(-1, 3).astype(float)
    if len(pixels) < 5:
        return (0, 0, 0)
    km = KMeans(n_clusters=1, n_init=3, random_state=0).fit(pixels)
    c  = km.cluster_centers_[0]
    return (int(round(c[0])), int(round(c[1])), int(round(c[2])))


# ─── Diff map ────────────────────────────────────────────────────────────────

def _write_diff_map(
    orig:   "np.ndarray",
    result: "np.ndarray",
    path:   Path,
) -> None:
    """
    Write a side-by-side comparison: [original | diff heatmap | result].
    Diff heatmap: green (identical) → yellow → red (maximum difference).
    """
    import numpy as np
    from PIL import Image

    diff   = np.abs(orig.astype(float) - result.astype(float))
    diff_g = diff.mean(axis=2) / 255.0  # grayscale normalized 0–1

    # Manual hot colormap: 0=green, 0.5=yellow, 1=red
    r_ch = np.clip(diff_g * 2.0,       0, 1)
    g_ch = np.clip(1.0 - diff_g * 1.5, 0, 1)
    b_ch = np.zeros_like(diff_g)

    heatmap = (np.stack([r_ch, g_ch, b_ch], axis=2) * 255).astype(np.uint8)

    # Side-by-side panel
    panel = np.concatenate([orig, heatmap, result], axis=1)
    Image.fromarray(panel).save(str(path))


# ─── Patch hints ──────────────────────────────────────────────────────────────

def _build_patch_hints(region_scores: list) -> list:
    """
    Build structured patch hints for failed regions in the JSON Patch Engine format.
    Each hint is: {element_id, property, expected_hex, actual_hex, dist}
    """
    hints = []
    for s in region_scores:
        if not s["match"]:
            exp = s["expected_rgb"]
            act = s["actual_rgb"]
            hints.append({
                "element_id":   f"region_{s['region_idx']}",
                "property":     "color_hex",
                "expected_hex": "#{:02X}{:02X}{:02X}".format(*exp),
                "actual_hex":   "#{:02X}{:02X}{:02X}".format(*act),
                "dist":         s["dist"],
            })
    return hints


# ─── Fallback ─────────────────────────────────────────────────────────────────

def _unavailable_result(msg: str) -> dict:
    return {
        "ssim_global":       None,
        "ssim_pass":         None,
        "color_dist_mean":   None,
        "region_match_rate": None,
        "region_scores":     [],
        "diff_map_path":     None,
        "patch_hints":       [],
        "error":             f"Dependencias ausentes: {msg}",
    }


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    _usage = (
        f"Uso: python {Path(__file__).name} <original> <resultado_compilado> [cover_analysis.json]\n\n"
        "Compara a imagem original com o PDF compilado (como PNG) e exibe metricas.\n\n"
        "Exemplo:\n"
        "  python visual_comparator.py capas_teste/capa_teste4.png resultado.png\n"
        "  python visual_comparator.py capa.png res.png automation/output/cover_analysis.json"
    )

    if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):
        print(_usage)
        sys.exit(0)

    _orig    = sys.argv[1]
    _result  = sys.argv[2]
    _anal    = None

    if len(sys.argv) > 3:
        try:
            _anal = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[!] Nao foi possivel carregar analise: {e}")

    print(f"[COMPARE] {Path(_orig).name}  vs  {Path(_result).name}")
    _report = compare(_orig, _result, _anal)

    if _report.get("error"):
        print(f"\n[ERRO] {_report['error']}")
        print("Instale: pip install scikit-image scikit-learn numpy Pillow")
        sys.exit(1)

    print(f"\n  SSIM global     : {_report['ssim_global']:.4f}"
          f"  ({'PASS' if _report['ssim_pass'] else 'FAIL'} >= {_report['ssim_threshold']})")
    print(f"  Color dist mean : {_report['color_dist_mean']:.1f} RGB units")
    print(f"  Region match    : {_report['region_match_rate'] * 100:.1f}%"
          f"  ({sum(s['match'] for s in _report['region_scores'])}"
          f"/{len(_report['region_scores'])} regioes)")

    if _report["diff_map_path"]:
        print(f"  Diff map        : {_report['diff_map_path']}")

    if _report["patch_hints"]:
        print(f"\n  {len(_report['patch_hints'])} regiao(oes) com cor incorreta:")
        for h in _report["patch_hints"]:
            print(f"    {h['element_id']:12s}  esperado={h['expected_hex']}"
                  f"  obtido={h['actual_hex']}  dist={h['dist']:.0f}")
    else:
        print("\n  Todas as regioes com cor correta.")

    print(f"\n[{'PASS' if _report['ssim_pass'] else 'FAIL'}] "
          f"SSIM={_report['ssim_global']:.4f}")
    print(json.dumps(_report, ensure_ascii=False, indent=2))
