#!/usr/bin/env python3
"""
image_analyzer.py — CV pre-render analysis for cover images.

Analyzes a cover image BEFORE calling any VLM, extracting:
  - Dominant color palette  (K-means, exact hex values)
  - Color region bounding boxes with shape classification
  - Layout structure  (horizontal bands: graphic zone vs. text zone)
  - High-variance zones that likely contain text
  - Logo presence heuristic

Output: structured dict + natural language summary for VLM context injection.

CLI:
    python image_analyzer.py <image.png>           # prints summary
    python image_analyzer.py <image.png> --json    # prints full JSON

Dependencies (all pip-installable, no system binary required):
    pip install Pillow numpy scikit-learn scikit-image
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
    from sklearn.cluster import KMeans
    from skimage import measure
    _HAVE_CV = True
except ImportError:
    _HAVE_CV = False


# ─── Constants ────────────────────────────────────────────────────────────────

_THUMB_W = 300
_THUMB_H = 450
_N_COLORS = 8
_MIN_REGION_AREA_FRAC = 0.015   # ignore regions smaller than 1.5% of image (was 2.5%)
_TEXT_VARIANCE_THRESH = 600     # local pixel variance threshold for text detection
_LOGO_VARIANCE_THRESH = 1200    # higher threshold for logo detection in top strip
_A4_RATIO = 297 / 210           # ≈ 1.414

# Region detection tuning
_MASK_COLOR_TOL  = 25    # tighter mask tolerance (was 40) to reduce boundary bleed
_RECT_FILL_RATIO = 0.68  # fill_ratio >= this → rectangle (was 0.88, too strict)
_GRID_MIN_LINES  = 2     # minimum grid lines detected to trust grid mode


# ─── Public API ───────────────────────────────────────────────────────────────

def analyze_image(
    path: "str | Path",
    canvas_w_cm: "float | None" = None,
    canvas_h_cm: "float | None" = None,
) -> dict:
    """
    Analyze a cover image using CV and return a structured dict.

    Parameters
    ----------
    path         : image path (PNG/JPEG/WEBP)
    canvas_w_cm  : desired output canvas width in cm (e.g. 21.0 for A4).
                   When given, all bbox_cm coordinates are relative to THIS
                   canvas, not the image's physical DPI-derived size.
    canvas_h_cm  : desired output canvas height in cm (e.g. 29.7 for A4).

    Returns a fallback dict (with cv_available=False) when the required
    libraries are not installed — caller can always read summary_text safely.

    Returned keys
    -------------
    format        : dimensions, DPI, orientation, format guess
    colors        : K-means palette — [{hex, rgb, coverage}, ...] desc by coverage
    regions       : large color regions — [{color_hex, shape_type, bbox_cm, area_pct}, ...]
    layout        : detected layout type + band brightness stats
    text_zones    : high-variance rectangular zones likely containing text
    has_logo      : bool heuristic
    summary_text  : natural language description ready for VLM injection
    cv_available  : bool — False when numpy/sklearn/skimage are missing
    """
    path = Path(path).resolve()

    if not _HAVE_CV:
        return _fallback_no_cv(path)

    img = Image.open(path).convert("RGB")
    w_px, h_px = img.size

    raw_dpi = img.info.get("dpi")
    dpi     = float(raw_dpi[0]) if isinstance(raw_dpi, (tuple, list)) and raw_dpi[0] else 150.0
    # Physical dimensions (for reporting only)
    phys_w_cm = round(w_px / dpi * 2.54, 2)
    phys_h_cm = round(h_px / dpi * 2.54, 2)

    # Canvas dimensions — what bbox_cm coordinates are relative to.
    # If caller supplies A4 (21×29.7), all region/text-zone coordinates
    # will be in A4 cm space, matching the TikZ canvas exactly.
    w_cm = canvas_w_cm if canvas_w_cm is not None else phys_w_cm
    h_cm = canvas_h_cm if canvas_h_cm is not None else phys_h_cm

    arr = np.array(img)  # (H, W, 3) uint8

    colors     = _extract_colors(img)
    regions    = _extract_regions(arr, colors, w_px, h_px, w_cm, h_cm)
    layout     = _analyze_layout(arr, h_px, w_px)
    text_zones = _detect_text_zones(arr, h_px, w_px, w_cm, h_cm)
    has_logo   = _detect_logo(arr, h_px, w_px)

    result = {
        "format": {
            "width_px":     w_px,
            "height_px":    h_px,
            "width_cm":     phys_w_cm,   # physical, for reference
            "height_cm":    phys_h_cm,
            "canvas_w_cm":  w_cm,        # canvas coordinates used for bboxes
            "canvas_h_cm":  h_cm,
            "dpi":          dpi,
            "orientation":  "portrait" if h_px >= w_px else "landscape",
            "format_guess": _guess_format(w_cm, h_cm),
        },
        "colors":       colors,
        "regions":      regions,
        "layout":       layout,
        "text_zones":   text_zones,
        "has_logo":     has_logo,
        "cv_available": True,
    }
    result["summary_text"] = _build_summary(path, result)
    return result


# ─── Color extraction ─────────────────────────────────────────────────────────

def _extract_colors(img: "Image.Image") -> list[dict]:
    """K-means clustering on a thumbnail. Returns list sorted by coverage desc."""
    thumb  = img.resize((_THUMB_W, _THUMB_H), Image.LANCZOS)
    pixels = np.array(thumb).reshape(-1, 3).astype(float)

    km = KMeans(n_clusters=_N_COLORS, n_init=10, random_state=42)
    km.fit(pixels)

    labels  = km.labels_
    centers = km.cluster_centers_.round().astype(int)
    total   = len(labels)

    colors = []
    for i, center in enumerate(centers):
        count  = int(np.sum(labels == i))
        r, g, b = int(center[0]), int(center[1]), int(center[2])
        colors.append({
            "hex":      f"#{r:02X}{g:02X}{b:02X}",
            "rgb":      [r, g, b],
            "coverage": round(count / total, 4),
        })

    colors.sort(key=lambda c: c["coverage"], reverse=True)
    return colors


# ─── Region extraction ────────────────────────────────────────────────────────

def _color_mask(arr: "np.ndarray", rgb: list[int], tol: int = 40) -> "np.ndarray":
    diff = np.abs(arr.astype(int) - np.array(rgb, dtype=int))
    return (diff[:, :, 0] < tol) & (diff[:, :, 1] < tol) & (diff[:, :, 2] < tol)


def _classify_shape(prop, roi: "np.ndarray") -> str:
    """Classify a connected region as rectangle, triangle, circle, or polygon."""
    roi_h, roi_w = roi.shape
    if roi_h == 0 or roi_w == 0:
        return "polygon"

    fill_ratio = prop.area / (roi_h * roi_w)
    circularity = (
        4 * math.pi * prop.area / (prop.perimeter ** 2)
        if prop.perimeter > 0 else 0.0
    )

    if circularity > 0.75:
        return "circle"
    if fill_ratio >= _RECT_FILL_RATIO:   # lowered from 0.88 → 0.68
        return "rectangle"
    if 0.35 <= fill_ratio < _RECT_FILL_RATIO:
        return "triangle"
    return "polygon"


def _extract_regions(
    arr: "np.ndarray",
    colors: list[dict],
    w_px: int, h_px: int,
    w_cm: float, h_cm: float,
) -> list[dict]:
    # ── Try grid-line detection first ────────────────────────────────────────
    grid_regions = _detect_grid_blocks(arr, w_px, h_px, w_cm, h_cm, palette=colors)
    if len(grid_regions) >= 4:
        grid_regions.sort(key=lambda r: r["area_pct"], reverse=True)
        return grid_regions[:30]

    # ── Fallback: per-color connected components (improved) ───────────────
    from skimage.morphology import binary_closing, disk as sk_disk

    min_area = w_px * h_px * _MIN_REGION_AREA_FRAC
    regions  = []

    for color_info in colors:
        # Tighter tolerance reduces bleed between adjacent differently-colored blocks
        mask = _color_mask(arr, color_info["rgb"], tol=_MASK_COLOR_TOL)

        # Morphological closing fills small gaps at block boundaries (anti-aliasing,
        # JPEG artifacts) so rectangular blocks don't split into disconnected fragments
        mask = binary_closing(mask, sk_disk(3))

        # 4-connectivity (not 8) avoids diagonal-corner connections between blocks
        labeled = measure.label(mask, connectivity=1)
        props   = measure.regionprops(labeled)

        for prop in props:
            if prop.area < min_area:
                continue
            minr, minc, maxr, maxc = prop.bbox
            shape = _classify_shape(prop, mask[minr:maxr, minc:maxc])

            regions.append({
                "color_hex":  color_info["hex"],
                "shape_type": shape,
                "bbox_cm": {
                    "x": round(minc / w_px * w_cm, 2),
                    "y": round((h_px - maxr) / h_px * h_cm, 2),
                    "w": round((maxc - minc) / w_px * w_cm, 2),
                    "h": round((maxr - minr) / h_px * h_cm, 2),
                },
                "bbox_px": {
                    "x": minc, "y": minr,
                    "w": maxc - minc, "h": maxr - minr,
                },
                "area_pct": round(prop.area / (w_px * h_px), 4),
            })

    regions.sort(key=lambda r: r["area_pct"], reverse=True)
    return regions[:30]


# ─── Grid-line detection ──────────────────────────────────────────────────────

def _detect_grid_blocks(
    arr: "np.ndarray",
    w_px: int, h_px: int,
    w_cm: float, h_cm: float,
    palette: "list[dict] | None" = None,
) -> list[dict]:
    """
    Detect rectangular blocks by finding strong horizontal/vertical edges via
    projection profiles (Sobel). Works well for Mondrian grids and pixel-art
    portraits where the block boundaries create sharp intensity transitions.

    Key detail: vertical line detection uses only the TOP 65% of the image.
    This avoids large text (e.g. "DAVID BOWIE") in the lower graphic area
    creating spurious vertical lines at every character boundary, which would
    split the left grid column into dozens of thin slivers.

    If `palette` is provided (K-means colors), each cell's color is snapped to
    the nearest palette entry instead of using the raw ROI median. This gives
    cleaner colors and reduces patch-engine corrections needed.

    Returns a list of region dicts (same schema as _extract_regions output),
    or [] if no clear grid is found.
    """
    from skimage.filters import sobel_h, sobel_v

    gray = arr.mean(axis=2)
    h_grad = np.abs(sobel_h(gray))
    v_grad = np.abs(sobel_v(gray))

    # ── Horizontal lines: top 73% to skip text-zone horizontal edges ────────
    # Large typography in the lower text band creates horizontal Sobel peaks
    # at every letter-top boundary, fragmenting the graphic section into thin
    # spurious cells. Using 73% captures the real graphic/text boundary
    # (typically at ~70-72%) while excluding text-area false peaks.
    graphic_rows_h = max(1, int(h_px * 0.73))
    h_profile = h_grad[:graphic_rows_h].mean(axis=1)

    # ── Vertical lines: only the top 65% to skip text-area character edges ─
    # Large typography in the lower graphic band creates a vertical Sobel peak
    # at every character boundary, fragmenting the left grid column.
    graphic_rows = max(1, int(h_px * 0.65))
    v_profile = v_grad[:graphic_rows].mean(axis=0)

    min_row_gap = max(h_px // 30, 8)
    min_col_gap = max(w_px // 30, 8)

    h_lines = _peak_indices_1d(h_profile, min_dist=min_row_gap)
    v_lines = _peak_indices_1d(v_profile, min_dist=min_col_gap)

    if len(h_lines) < _GRID_MIN_LINES and len(v_lines) < _GRID_MIN_LINES:
        return []

    # Refine each line to its exact local maximum (±5 px window), then snap to
    # the true RGB colour transition (fixes the ~1px Sobel offset and catches
    # equal-luminance edges the greyscale profile localises poorly).
    h_lines = [_refine_peak(h_profile, p, window=5) for p in h_lines]
    v_lines = [_refine_peak(v_profile, p, window=5) for p in v_lines]
    h_lines = [_snap_line_to_color_edge(arr, p, "h", w_px, h_px) for p in h_lines]
    v_lines = [_snap_line_to_color_edge(arr, p, "v", w_px, h_px) for p in v_lines]

    rows = sorted({0} | set(h_lines) | {h_px})
    cols = sorted({0} | set(v_lines) | {w_px})

    min_cell_area = w_px * h_px * _MIN_REGION_AREA_FRAC

    blocks = []
    for i in range(len(rows) - 1):
        r1, r2 = rows[i], rows[i + 1]
        if (r2 - r1) < h_px * 0.03:
            continue
        for j in range(len(cols) - 1):
            c1, c2 = cols[j], cols[j + 1]
            if (c2 - c1) < w_px * 0.03:
                continue
            cell_area = (r2 - r1) * (c2 - c1)
            if cell_area < min_cell_area:
                continue

            # Median color of cell interior (skip outermost 2px border to
            # avoid edge bleed from adjacent blocks)
            pad = 2
            roi = arr[r1 + pad:r2 - pad, c1 + pad:c2 - pad]
            if roi.size == 0:
                roi = arr[r1:r2, c1:c2]

            # Pre-compute bbox_cm for this cell (used by both paths below)
            cell_bbox = {
                "x": round(c1 / w_px * w_cm, 2),
                "y": round((h_px - r2) / h_px * h_cm, 2),
                "w": round((c2 - c1) / w_px * w_cm, 2),
                "h": round((r2 - r1) / h_px * h_cm, 2),
            }
            cell_px = {"x": c1, "y": r1, "w": c2 - c1, "h": r2 - r1}
            area_f  = round(cell_area / (w_px * h_px), 4)

            # Check for diagonal color split (high variance → potential triangle
            # pair). A split shows up as high variance in at least ONE channel;
            # averaging the three channels can mask a strong single-channel split
            # (e.g. magenta vs red differ almost only in blue, averaging to ~20).
            # Gate on the max-channel std instead: solid cells sit ≤3, splits ≥40.
            roi_std_max = float(roi.reshape(-1, 3).std(axis=0).max())
            if roi_std_max > 15:
                diag = _best_diagonal(roi, palette)
                if diag is not None:
                    diag_type, col_a, col_b = diag
                    # Two complementary triangles sharing the same bbox.
                    # diagonal_type tells tikz_generator which fill commands to use:
                    #   'slash'     → _cmd_triangle_ul + _cmd_triangle_lr  (/ pair)
                    #   'backslash' → _cmd_triangle_bl + _cmd_triangle_ur  (\ pair)
                    for col in (col_a, col_b):
                        blocks.append({
                            "color_hex":    col,
                            "shape_type":   "triangle",
                            "diagonal_type": diag_type,
                            "bbox_cm":      cell_bbox,
                            "bbox_px":      cell_px,
                            "area_pct":     round(area_f / 2, 4),
                            "source":       "grid",
                        })
                    continue

            dom = np.median(roi.reshape(-1, 3), axis=0).astype(int)

            # Snap to nearest K-means palette color if available
            hex_color = _snap_to_palette(dom, palette) if palette else \
                "#{:02X}{:02X}{:02X}".format(int(dom[0]), int(dom[1]), int(dom[2]))

            blocks.append({
                "color_hex":  hex_color,
                "shape_type": "rectangle",
                "bbox_cm":    cell_bbox,
                "bbox_px":    cell_px,
                "area_pct":   area_f,
                "source":     "grid",
            })

    return blocks


def _best_diagonal(
    roi:      "np.ndarray",
    palette:  "list[dict] | None",
    min_dist: int = 60,
) -> "tuple[str, str, str] | None":
    """
    Detect whether a rectangular cell ROI has a diagonal color division.

    Tries both the forward-slash (/) and backslash (\\) diagonals and picks
    the one whose two halves are more colour-homogeneous (lower within-group
    pixel variance) and more colour-distant from each other.

    Returns (diagonal_type, col_first, col_second) or None.

    diagonal_type = 'slash'     → / diagonal;  first=UL region, second=LR region
    diagonal_type = 'backslash' → \\ diagonal; first=NW region, second=SE region

    tikz_generator uses the type to choose the correct fill commands.
    """
    h, w = roi.shape[:2]
    if h < 20 or w < 20:
        return None

    pix = roi.reshape(h, w, 3).astype(float)
    rr, cc = np.mgrid[0:h, 0:w]

    # /  masks: upper-left (contains TL) and lower-right (contains BR)
    fs_a = (rr * w + cc * h) <  (h * w)   # UL
    fs_b = (rr * w + cc * h) >  (h * w)   # LR

    # \\ masks: NW (contains BL: r*w>c*h) and SE (contains TR: r*w<c*h)
    bs_a = rr * w >  cc * h               # NW = lower-left in TikZ
    bs_b = rr * w <  cc * h               # SE = upper-right in TikZ

    best: "dict | None" = None

    for diag_name, mask_a, mask_b in (
        ("slash",     fs_a, fs_b),
        ("backslash", bs_a, bs_b),
    ):
        pa = pix[mask_a].reshape(-1, 3)
        pb = pix[mask_b].reshape(-1, 3)
        if pa.shape[0] < 20 or pb.shape[0] < 20:
            continue

        med_a = np.median(pa, axis=0)
        med_b = np.median(pb, axis=0)

        diff = float(np.sqrt(((med_a - med_b) ** 2).sum()))
        if diff < min_dist:
            continue

        # Within-group homogeneity (lower = each half is more uniform)
        var_a = float(pa.var(axis=0).mean())
        var_b = float(pb.var(axis=0).mean())
        avg_var = (var_a + var_b) / 2 + 1e-6

        score = diff / avg_var  # higher = better diagonal candidate

        col_a = _snap_to_palette(med_a.astype(int), palette) if palette else \
            "#{:02X}{:02X}{:02X}".format(int(med_a[0]), int(med_a[1]), int(med_a[2]))
        col_b = _snap_to_palette(med_b.astype(int), palette) if palette else \
            "#{:02X}{:02X}{:02X}".format(int(med_b[0]), int(med_b[1]), int(med_b[2]))

        if col_a == col_b:
            continue

        if best is None or score > best["score"]:
            best = {"type": diag_name, "col_a": col_a, "col_b": col_b, "score": score}

    if best is None:
        return None
    return (best["type"], best["col_a"], best["col_b"])


def _refine_peak(profile: "np.ndarray", rough: int, window: int = 5) -> int:
    """Return the index of the true maximum within ±window of rough."""
    start = max(0, rough - window)
    end   = min(len(profile), rough + window + 1)
    return int(start + np.argmax(profile[start:end]))


def _snap_line_to_color_edge(
    arr:    "np.ndarray",
    pos:    int,
    axis:   str,
    w_px:   int,
    h_px:   int,
    window: int = 4,
) -> int:
    """
    Refine a grid line to the exact colour transition near `pos`.

    The greyscale Sobel peak can land a pixel off the true boundary and misses
    edges between equal-luminance colours (e.g. magenta vs red). Scanning the
    RGB colour difference between adjacent lines in a small window pins the
    boundary to where the block colour actually changes. The returned index `k`
    is the first line of the second block (colour differs most from `k-1`),
    matching the half-open [rows[i], rows[i+1]) cell convention.
    """
    graphic = max(1, int(h_px * 0.65))   # ignore the text band's own edges
    if axis == "h":
        lo, hi = max(1, pos - window), min(h_px, pos + window + 1)
        diffs = [
            (float(np.abs(arr[r].astype(int) - arr[r - 1].astype(int)).sum(axis=1).mean()), r)
            for r in range(lo, hi)
        ]
    else:
        lo, hi = max(1, pos - window), min(w_px, pos + window + 1)
        diffs = [
            (float(np.abs(arr[:graphic, c].astype(int) - arr[:graphic, c - 1].astype(int))
                   .sum(axis=1).mean()), c)
            for c in range(lo, hi)
        ]
    if not diffs:
        return pos
    return max(diffs, key=lambda t: t[0])[1]


def _snap_to_palette(
    rgb: "np.ndarray",
    palette: "list[dict] | None",
) -> str:
    """Return the hex of the nearest palette color by Euclidean RGB distance."""
    if not palette:
        return "#{:02X}{:02X}{:02X}".format(int(rgb[0]), int(rgb[1]), int(rgb[2]))
    best_hex  = palette[0]["hex"]
    best_dist = float("inf")
    for entry in palette:
        pr, pg, pb = entry["rgb"]
        d = ((int(rgb[0]) - pr) ** 2 +
             (int(rgb[1]) - pg) ** 2 +
             (int(rgb[2]) - pb) ** 2) ** 0.5
        if d < best_dist:
            best_dist = d
            best_hex  = entry["hex"]
    return best_hex


def _peak_indices_1d(profile: "np.ndarray", min_dist: int) -> list:
    """
    Find local maxima in a 1D profile that exceed mean + 1.5·std.
    Enforces a minimum distance between consecutive peaks.
    No scipy dependency.
    """
    threshold = float(profile.mean() + 1.5 * profile.std())
    peaks: list[int] = []
    n = len(profile)
    for i in range(1, n - 1):
        if (float(profile[i]) >= threshold
                and float(profile[i]) >= float(profile[i - 1])
                and float(profile[i]) >= float(profile[i + 1])):
            if not peaks or (i - peaks[-1]) >= min_dist:
                peaks.append(i)
    return peaks


# ─── Layout analysis ──────────────────────────────────────────────────────────

def _analyze_layout(arr: "np.ndarray", h_px: int, w_px: int) -> dict:
    """Detect dominant split: top/bottom or left/right."""
    n      = 20
    band_h = max(1, h_px // n)

    bands = [arr[i * band_h:(i + 1) * band_h] for i in range(n)]
    bright = [float(b.mean()) for b in bands]
    stds   = [float(b.std())  for b in bands]

    cut    = int(n * 0.70)
    top_b  = sum(bright[:cut]) / cut
    bot_b  = sum(bright[cut:]) / (n - cut)
    top_s  = sum(stds[:cut]) / cut
    bot_s  = sum(stds[cut:]) / (n - cut)
    v_delta = abs(top_b - bot_b)

    mid = w_px // 2
    left_b  = float(arr[:, :mid].mean())
    right_b = float(arr[:, mid:].mean())
    h_delta = abs(left_b - right_b)

    if v_delta >= h_delta * 0.8:
        if v_delta < 20:
            layout_type = "uniform"
        elif top_b < bot_b:
            layout_type = "top_graphic_bottom_text"
        else:
            layout_type = "top_text_bottom_graphic"
    else:
        if left_b < right_b:
            layout_type = "left_graphic_right_text"
        else:
            layout_type = "left_text_right_graphic"

    return {
        "type":              layout_type,
        "top_brightness":    round(top_b, 1),
        "bottom_brightness": round(bot_b, 1),
        "top_detail":        round(top_s, 1),
        "bottom_detail":     round(bot_s, 1),
        "vertical_delta":    round(v_delta, 1),
        "horizontal_delta":  round(h_delta, 1),
    }


# ─── Text zone detection ──────────────────────────────────────────────────────

def _detect_text_zones(
    arr: "np.ndarray",
    h_px: int, w_px: int,
    w_cm: float, h_cm: float,
) -> list[dict]:
    """Sliding-window variance: high local variance → likely text or fine detail."""
    gray    = arr.mean(axis=2)
    bh      = max(1, h_px // 16)
    bw      = max(1, w_px // 8)
    stride_h = max(1, bh // 2)
    stride_w = max(1, bw // 2)
    zones   = []

    for r in range(0, h_px - bh, stride_h):
        for c in range(0, w_px - bw, stride_w):
            var = float(gray[r:r + bh, c:c + bw].var())
            if var > _TEXT_VARIANCE_THRESH:
                zones.append({
                    "bbox_cm": {
                        "x": round(c / w_px * w_cm, 2),
                        "y": round((h_px - r - bh) / h_px * h_cm, 2),
                        "w": round(bw / w_px * w_cm, 2),
                        "h": round(bh / h_px * h_cm, 2),
                    },
                    "variance": round(var, 1),
                })

    zones.sort(key=lambda z: z["variance"], reverse=True)
    return zones[:10]


# ─── Logo heuristic ───────────────────────────────────────────────────────────

def _detect_logo(arr: "np.ndarray", h_px: int, w_px: int) -> bool:
    """High-variance small region in the top 20% → likely a logo."""
    strip = arr[:max(1, int(h_px * 0.20)), :].mean(axis=2)
    bh    = max(1, strip.shape[0] // 2)
    bw    = max(1, w_px // 8)
    max_v = 0.0

    for r in range(0, strip.shape[0] - bh + 1, bh):
        for c in range(0, w_px - bw + 1, bw):
            v = float(strip[r:r + bh, c:c + bw].var())
            if v > max_v:
                max_v = v

    return max_v > _LOGO_VARIANCE_THRESH


# ─── Summary builder ──────────────────────────────────────────────────────────

def _build_summary(path: Path, data: dict) -> str:
    fmt      = data["format"]
    colors   = data["colors"]
    regions  = data["regions"]
    layout   = data["layout"]
    text_z   = data["text_zones"]

    lines = [
        "══ PRE-ANALYSIS (CV, computed before VLM call) ══",
        f"File   : {path.name}",
        (
            f"Format : {fmt['format_guess']}  "
            f"{fmt['width_cm']}×{fmt['height_cm']} cm  "
            f"({fmt['width_px']}×{fmt['height_px']} px at {fmt['dpi']:.0f} dpi)  "
            f"{fmt['orientation']}"
        ),
        "",
        f"COLOR PALETTE — K-means k={_N_COLORS}:",
    ]

    for i, c in enumerate(colors, 1):
        bar = "█" * max(1, round(c["coverage"] * 20))
        lines.append(f"  {i:>2}. {c['hex']}  {bar:<20}  {c['coverage'] * 100:.1f}%")

    lt = layout["type"].replace("_", " ")
    lines += [
        "",
        f"LAYOUT : {lt}",
        (
            f"  Top 70% : brightness={layout['top_brightness']:.0f}  "
            f"detail={layout['top_detail']:.0f}"
        ),
        (
            f"  Bot 30% : brightness={layout['bottom_brightness']:.0f}  "
            f"detail={layout['bottom_detail']:.0f}"
        ),
    ]

    if regions:
        lines += ["", f"GEOMETRIC REGIONS (≥{_MIN_REGION_AREA_FRAC * 100:.0f}% area, {len(regions)} detected):"]
        for reg in regions[:14]:
            b = reg["bbox_cm"]
            lines.append(
                f"  {reg['color_hex']}  {reg['shape_type']:11}  "
                f"x={b['x']:5.1f} y={b['y']:5.1f} w={b['w']:5.1f} h={b['h']:5.1f}  "
                f"area={reg['area_pct'] * 100:.1f}%"
            )

    if text_z:
        lines += ["", f"HIGH-VARIANCE ZONES (likely text/detail, top {len(text_z)}):"]
        for tz in text_z[:5]:
            b = tz["bbox_cm"]
            lines.append(
                f"  x={b['x']:.1f} y={b['y']:.1f} w={b['w']:.1f} h={b['h']:.1f}  "
                f"var={tz['variance']:.0f}"
            )

    lines += [
        "",
        f"LOGO DETECTED : {'YES (heuristic — verify visually)' if data['has_logo'] else 'NO'}",
        "══ END PRE-ANALYSIS ══",
    ]
    return "\n".join(lines)


# ─── Utilities ────────────────────────────────────────────────────────────────

def _guess_format(w_cm: float, h_cm: float) -> str:
    if w_cm == 0:
        return "custom"
    ratio = h_cm / w_cm
    if abs(ratio - _A4_RATIO) < 0.12:
        return "A4"
    if abs(ratio - 1.294) < 0.12:
        return "US Letter"
    if abs(ratio - 1.0) < 0.06:
        return "Square"
    return f"{h_cm:.0f}×{w_cm:.0f}cm"


def _fallback_no_cv(path: Path) -> dict:
    try:
        from PIL import Image  # noqa: PLC0415
        img = Image.open(path)
        w_px, h_px = img.size
    except Exception:
        w_px, h_px = 0, 0

    msg = (
        "[PRE-ANALYSIS SKIPPED — install: pip install Pillow numpy scikit-learn scikit-image]\n"
        f"File: {path.name}  Size: {w_px}×{h_px} px"
    )
    return {
        "format":       {
            "width_px": w_px, "height_px": h_px,
            "width_cm": 0, "height_cm": 0, "dpi": 0,
            "orientation": "portrait", "format_guess": "unknown",
        },
        "colors":       [],
        "regions":      [],
        "layout":       {"type": "unknown"},
        "text_zones":   [],
        "has_logo":     False,
        "summary_text": msg,
        "cv_available": False,
    }


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(f"Usage: python {Path(__file__).name} <image.png> [--json]")
        sys.exit(0)

    result = analyze_image(sys.argv[1])
    if "--json" in sys.argv:
        # Remove rgb lists to keep output clean
        clean = {k: v for k, v in result.items() if k != "summary_text"}
        print(json.dumps(clean, indent=2, default=str))
    else:
        print(result.get("summary_text", "[no summary]"))
