#!/usr/bin/env python3
"""
pattern_detector.py — Detect repetition and symmetry in cover region lists.

Takes the `regions` list produced by image_analyzer and looks for:
  1. Grid repetition  — N similar bboxes regularly spaced in X or Y
  2. Horizontal mirror symmetry — left/right regions that are reflections
  3. Vertical stripe repetition — color bands stacked vertically

When a pattern is found, the affected regions are tagged with a `pattern`
key that tikz_generator uses to emit a \foreach loop instead of N individual
\fill commands.

Public API:
    detect_patterns(regions, width_cm=21.0, height_cm=29.7) -> list[dict]

Each input region dict is returned unchanged if no pattern is found, or
enriched with:
    pattern         str  — "grid" | "h_mirror" | "v_stripes"
    foreach_axis    str  — "x" | "y" | "xy"  (for grid/stripes)
    foreach_step_cm float — spacing between repetitions
    foreach_count   int   — number of repetitions
    foreach_anchor  dict  — bbox of the first element in the sequence
"""

from pathlib import Path

# Tolerance for considering two measurements "equal" (in cm)
_SPACING_TOL_CM   = 0.4
# Minimum number of similar elements to declare a pattern
_MIN_REPEAT_COUNT = 3
# Maximum relative size difference between "similar" regions (fraction)
_SIZE_TOL_FRAC    = 0.20
# Maximum RGB Euclidean distance for two regions to be considered "same color"
_COLOR_TOL_RGB    = 35


# ─── Public entry point ───────────────────────────────────────────────────────

def detect_patterns(
    regions:    "list[dict]",
    width_cm:   float = 21.0,
    height_cm:  float = 29.7,
) -> "list[dict]":
    """
    Analyse a list of region dicts (from image_analyzer) and tag repeated
    groups with pattern metadata.

    Parameters
    ----------
    regions   : list of region dicts each with at least bbox_cm {x,y,w,h}
    width_cm  : canvas width in cm  (used for symmetry axis)
    height_cm : canvas height in cm (unused currently, kept for future use)

    Returns
    -------
    Same list with matching regions enriched with pattern fields.
    Non-matching regions are returned unchanged.
    """
    if not regions:
        return regions

    regions = [r.copy() for r in regions]

    # Grid cells (source="grid") come from Sobel line detection and each have
    # a unique color and position derived from the actual image structure.
    # They are always rendered as individual \fill commands — \foreach loops
    # would require identical dimensions and colors across all repetitions,
    # which is never the case for a Mondrian/pixelated-portrait grid.
    grid_cells = [r for r in regions if r.get("source") == "grid"]
    non_grid   = [r for r in regions if r.get("source") != "grid"]

    # Run each detector in order of confidence; once a region is tagged, skip it
    non_grid = _detect_v_stripes(non_grid)
    non_grid = _detect_grid(non_grid)
    non_grid = _detect_h_mirror(non_grid, width_cm)

    return grid_cells + non_grid


# ─── Vertical stripe detector ─────────────────────────────────────────────────

def _detect_v_stripes(regions: "list[dict]") -> "list[dict]":
    """
    Detect full-width color bands stacked vertically (common in Swiss Design).

    Criterion: regions whose bbox width spans ≥ 85% of the canvas width AND
    whose heights are within _SIZE_TOL_FRAC of each other AND whose Y
    positions are regularly spaced.
    """
    # Full-width: regions wider than any specific threshold are detected via
    # width_fraction if available; otherwise use absolute width > 15 cm
    wide = [r for r in regions if r.get("bbox_cm", {}).get("w", 0) >= 15.0]
    if len(wide) < _MIN_REPEAT_COUNT:
        return regions

    # Sort by Y (bottom to top in TikZ coords)
    wide.sort(key=lambda r: r["bbox_cm"]["y"])

    groups = _find_regular_sequence(wide, axis="y")
    for group_indices, step in groups:
        for idx in group_indices:
            r = wide[idx]
            _tag_region(
                regions, r,
                pattern="v_stripes",
                foreach_axis="y",
                foreach_step_cm=round(step, 3),
                foreach_count=len(group_indices),
                foreach_anchor=wide[group_indices[0]]["bbox_cm"],
            )
    return regions


# ─── Grid / repetition detector ───────────────────────────────────────────────

def _detect_grid(regions: "list[dict]") -> "list[dict]":
    """
    Detect a regular grid of similarly sized regions (e.g. 3×3 blocks).

    Groups regions by similar (w, h) dimensions, then checks spacing in
    X and Y independently.
    """
    untagged = [r for r in regions if "pattern" not in r]
    if len(untagged) < _MIN_REPEAT_COUNT:
        return regions

    # Group by similar size
    size_groups = _cluster_by_size(untagged)
    for group in size_groups:
        if len(group) < _MIN_REPEAT_COUNT:
            continue

        # Try X-axis repetition
        group_x = sorted(group, key=lambda r: r["bbox_cm"]["x"])
        x_seqs  = _find_regular_sequence(group_x, axis="x")
        for seq_idx, step in x_seqs:
            members = [group_x[i] for i in seq_idx]
            for r in members:
                _tag_region(
                    regions, r,
                    pattern="grid",
                    foreach_axis="x",
                    foreach_step_cm=round(step, 3),
                    foreach_count=len(seq_idx),
                    foreach_anchor=group_x[seq_idx[0]]["bbox_cm"],
                )

        # Try Y-axis repetition (on still-untagged members)
        group_y = sorted(
            [r for r in group if "pattern" not in r],
            key=lambda r: r["bbox_cm"]["y"],
        )
        y_seqs = _find_regular_sequence(group_y, axis="y")
        for seq_idx, step in y_seqs:
            members = [group_y[i] for i in seq_idx]
            for r in members:
                _tag_region(
                    regions, r,
                    pattern="grid",
                    foreach_axis="y",
                    foreach_step_cm=round(step, 3),
                    foreach_count=len(seq_idx),
                    foreach_anchor=group_y[seq_idx[0]]["bbox_cm"],
                )

    return regions


# ─── Horizontal mirror symmetry detector ──────────────────────────────────────

def _detect_h_mirror(regions: "list[dict]", width_cm: float) -> "list[dict]":
    """
    Detect left/right mirrored region pairs around the vertical center axis.

    For each untagged region, look for a counterpart whose:
      - X center is mirrored: x_mirror = width_cm - (x + w)
      - Y center, width, height are within tolerance
    """
    untagged = [r for r in regions if "pattern" not in r]
    axis_x   = width_cm / 2.0
    matched  = set()

    for i, r in enumerate(untagged):
        if i in matched:
            continue
        bx = r["bbox_cm"]
        cx = bx["x"] + bx["w"] / 2.0
        cy = bx["y"] + bx["h"] / 2.0

        mirror_cx = width_cm - cx

        for j, s in enumerate(untagged):
            if j <= i or j in matched:
                continue
            bs   = s["bbox_cm"]
            scx  = bs["x"] + bs["w"] / 2.0
            scy  = bs["y"] + bs["h"] / 2.0

            cx_ok = abs(scx - mirror_cx)   < _SPACING_TOL_CM
            cy_ok = abs(scy - cy)          < _SPACING_TOL_CM
            w_ok  = _rel_diff(bx["w"], bs["w"]) < _SIZE_TOL_FRAC
            h_ok  = _rel_diff(bx["h"], bs["h"]) < _SIZE_TOL_FRAC

            if cx_ok and cy_ok and w_ok and h_ok:
                matched.add(i)
                matched.add(j)
                for reg in (r, s):
                    _tag_region(
                        regions, reg,
                        pattern="h_mirror",
                        foreach_axis="x",
                        foreach_step_cm=round(abs(mirror_cx - cx) * 2, 3),
                        foreach_count=2,
                        foreach_anchor=r["bbox_cm"],
                    )
                break

    return regions


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _find_regular_sequence(
    sorted_regions: "list[dict]",
    axis: str,
) -> "list[tuple[list[int], float]]":
    """
    Given a list of regions sorted by `axis` (x or y), find the longest
    subsequence where the spacing between consecutive elements is constant
    within _SPACING_TOL_CM.

    Returns list of (index_list, step_cm) tuples for valid sequences.
    """
    if len(sorted_regions) < 2:
        return []

    key = "x" if axis == "x" else "y"
    centers = [r["bbox_cm"][key] + r["bbox_cm"]["w" if axis == "x" else "h"] / 2.0
               for r in sorted_regions]

    results = []
    n = len(centers)
    used = set()

    for start in range(n - 1):
        if start in used:
            continue
        step = centers[start + 1] - centers[start]
        if step <= 0:
            continue

        seq = [start, start + 1]
        for k in range(start + 2, n):
            expected = centers[seq[-1]] + step
            if abs(centers[k] - expected) < _SPACING_TOL_CM:
                seq.append(k)

        if len(seq) >= _MIN_REPEAT_COUNT:
            results.append((seq, step))
            used.update(seq)

    return results


def _cluster_by_size(regions: "list[dict]") -> "list[list[dict]]":
    """
    Group regions by similar (w, h) dimensions AND similar color.
    Requires matching color so that adjacent differently-colored grid cells
    are never grouped into the same \foreach loop.
    """
    groups: list[list[dict]] = []
    assigned = [False] * len(regions)

    for i, r in enumerate(regions):
        if assigned[i]:
            continue
        group = [r]
        assigned[i] = True
        for j, s in enumerate(regions):
            if assigned[j] or i == j:
                continue
            w_ok = _rel_diff(r["bbox_cm"]["w"], s["bbox_cm"]["w"]) < _SIZE_TOL_FRAC
            h_ok = _rel_diff(r["bbox_cm"]["h"], s["bbox_cm"]["h"]) < _SIZE_TOL_FRAC
            c_ok = _color_dist(
                r.get("color_hex", "#000000"),
                s.get("color_hex", "#000000"),
            ) < _COLOR_TOL_RGB
            if w_ok and h_ok and c_ok:
                group.append(s)
                assigned[j] = True
        if len(group) >= 2:
            groups.append(group)

    return groups


def _color_dist(hex_a: str, hex_b: str) -> float:
    """RGB Euclidean distance between two hex color strings."""
    def _parse(h: str) -> "tuple[int,int,int]":
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    a, b = _parse(hex_a), _parse(hex_b)
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _rel_diff(a: float, b: float) -> float:
    """Relative difference between two values (0 if both zero)."""
    denom = max(abs(a), abs(b))
    return abs(a - b) / denom if denom > 1e-9 else 0.0


def _tag_region(
    all_regions: "list[dict]",
    target:      dict,
    **kwargs,
) -> None:
    """
    Find `target` in `all_regions` by identity and add kwargs as keys.
    Uses object identity (is) so copies and mutations don't confuse matching.
    """
    for r in all_regions:
        if r is target:
            r.update(kwargs)
            return


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    _usage = (
        f"Uso: python {Path(__file__).name} <imagem> [width_cm] [height_cm]\n\n"
        "Detecta padroes de repeticao nas regioes coloridas da imagem.\n"
        "Requer: numpy, scikit-learn, scikit-image (para image_analyzer)\n\n"
        "Exemplo:\n"
        "  python pattern_detector.py capas_teste/capa_teste4.png"
    )

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(_usage)
        sys.exit(0)

    # Load regions via image_analyzer (same directory)
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "image_analyzer", Path(__file__).parent / "image_analyzer.py"
    )
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)

    _path    = sys.argv[1]
    _wcm     = float(sys.argv[2]) if len(sys.argv) > 2 else 21.0
    _hcm     = float(sys.argv[3]) if len(sys.argv) > 3 else 29.7

    print(f"[PATTERN] Analisando: {_path}")
    _cv      = _mod.analyze_image(_path)
    _regions = _cv.get("regions", [])

    if not _regions:
        print("Nenhuma regiao detectada (verifique dependencias do image_analyzer).")
        sys.exit(0)

    print(f"  {len(_regions)} regiao(es) detectada(s). Verificando padroes…\n")
    _tagged = detect_patterns(_regions, _wcm, _hcm)

    _with_pattern = [r for r in _tagged if "pattern" in r]
    _without      = [r for r in _tagged if "pattern" not in r]

    print(f"  Com padrao  : {len(_with_pattern)}")
    print(f"  Sem padrao  : {len(_without)}\n")

    if _with_pattern:
        print("--- Regioes com padrao ---")
        print(json.dumps(_with_pattern, ensure_ascii=False, indent=2))
    else:
        print("Nenhum padrao de repeticao detectado nesta imagem.")
        print("(Normal para capas com blocos de cor unicos)")
