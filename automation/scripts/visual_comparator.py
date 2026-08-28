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
import os
from pathlib import Path

_OUTPUT_DIR    = Path(__file__).resolve().parent.parent / "output"
_SSIM_THRESH   = 0.82   # minimum acceptable SSIM
_COLOR_MATCH   = 40.0   # max RGB distance to count a region color as "reproduced"
_N_PALETTE     = 8      # K-means clusters for palette comparison

# `score` is the single number the correction LOOP optimises. SSIM alone is area-
# weighted (a big matching background inflates it), so content_match / content_iou
# — which score only the foreground — carry most of the weight. This is what stops
# the loop from "improving the background while wrecking the content".
# Calibrated against the USER'S OWN classification of all 20 covers (Boas / Ok / Pessimas,
# 2026-08-19), scored by pairwise concordance over the 123 cross-class pairs:
#     ssim 80.5% · structural 76.4% · content_match 71.5% · content_iou 67.5%
#     text_match 51.2% (chance — it carries NO information about the human verdict)
#     the previous 0.30/0.50/0.20 composite: 71.5%
# Every weighting with ssim >= 0.8 beats that by 8+ points, so the DIRECTION is solid even
# though the exact split is not identifiable from only 20 covers. `structural` is kept because
# it adds 2.4pp over ssim alone AND because it inherits content_match's protective job: SSIM is
# area-weighted, so a mostly-background cover could climb by perfecting the background, and a
# render with no shapes to match scores ~0 on structural.
# ⚠️ The old doctrine "SSIM alone misleads" was TRUE when covers were background with the
# content missing entirely. With structure largely right it aged out, and had never been
# re-measured. Re-measure a doctrine before building on it.
# ⚠️ REVERTED 2026-08-19, and the lesson is worth more than the weights.
# These were briefly 0.75 ssim / 0.25 structural, calibrated so the metric ORDERS the 20
# covers the way the user does (71.5% → 82.9% pairwise concordance, adversarial bench 4/4).
# It passed that test and STILL had to be reverted: once the LOOP optimised it, four covers
# got visibly worse (capa2 and capa15 lost text blocks, capa10 lost its 102pt title,
# capa5 went flat). Mechanism: neither ssim nor structural notices MISSING TEXT — ssim barely
# reacts to thin type and structural matches coloured blobs — so DELETING text became free and
# the loop deleted it. `_select_text` removing capa10's fake "UUU" was the same bug showing its
# good half.
# **A metric can be a good RANKER and a bad OPTIMISATION TARGET.** Ranking agreement is not a
# sufficient acceptance test: run the loop with the candidate and look at the renders too.
# structural_match() is kept and REPORTED — it is a genuinely good signal (76.4% on its own)
# and belongs in a future Score that also carries a content/text-presence term.
_SCORE_W = {"ssim": 0.30, "content_match": 0.50, "content_iou": 0.20}


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

    # ── 1b. Content metrics (SSIM is area-weighted, so a large matching
    #        background inflates it while missing foreground — circles, text —
    #        barely moves it. These score ONLY the non-background pixels.) ─────
    content_match, content_iou, content_match_tol = _content_metrics(orig, result)

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

    # text_match: the Fase-5 text gate (None when the cover has no text boxes).
    tboxes = _text_boxes_from_analysis(analysis, W, H, orig.shape)
    tmatch = text_match(orig, result, tboxes)
    # per-box ink F1 (aligned with text_elements order) — a text.add is judged on the box
    # it appended (the last one), which the diluted mean can't show.
    tbox_scores = [round(_text_box_f1(orig, result, b), 4) for b in tboxes]

    # The content term scores TYPE with the tolerant metric and everything else strictly,
    # mixed by each part's share of the CONTENT (see _content_split). Before this the Score
    # graded type pixel-to-pixel and text_match — which grades it properly — was computed,
    # reported, and given zero weight.
    content_eff = content_match
    if tmatch is not None and tboxes:
        nontext, tshare = _content_split(orig, result, tboxes)
        if nontext is None:                      # the design is type all the way through
            content_eff = tmatch if tshare > 0 else content_match
        elif tshare > 0:
            content_eff = (1.0 - tshare) * nontext + tshare * tmatch

    struct_val = structural_match(orig, result)      # reported, not scored (see _SCORE_W)
    score = (_SCORE_W["ssim"]            * ssim_val
             + _SCORE_W["content_match"] * content_eff
             + _SCORE_W["content_iou"]   * content_iou)

    return {
        "score":             round(score, 4),
        "score_pass":        score >= thresh,
        "ssim_global":       round(ssim_val, 4),
        "ssim_pass":         ssim_val >= thresh,
        "ssim_threshold":    thresh,
        "structural_match":  round(struct_val, 4),
        "content_match":     round(content_match, 4),
        "content_effective": round(content_eff, 4),   # what the Score actually uses
        "content_match_tol": round(content_match_tol, 4),   # ±px-tolerant (see the constant)
        "content_iou":       round(content_iou, 4),
        "text_match":        round(tmatch, 4) if tmatch is not None else None,
        "text_box_scores":   tbox_scores,
        "color_dist_mean":   round(color_dist, 2),
        "region_match_rate": round(match_rate, 3),
        "region_scores":     region_scores,
        "diff_map_path":     str(diff_path),
        "patch_hints":       patch_hints,
    }


# ─── Content metrics (foreground-only) ───────────────────────────────────────

_CONTENT_BG_DIST = 60    # a pixel this far from the background colour is "content"
_CONTENT_MATCH_D = 60    # render vs original within this RGB dist = a match

# SPATIAL TOLERANCE (2026-08-06). content_match is POINTWISE, so it has no tolerance for
# sub-pixel raster differences — and comparing rasterised vector art against a photo/scan
# always produces them along every edge. Thin strokes and CURVES are all edge, so they are
# punished hardest: capa3's faithful circle lattice scored 0.611 while a structurally WRONG
# grid of bars scored 0.747, purely because straight edges land on the pixel grid. This
# variant accepts a content pixel when the render carries its colour anywhere within
# ±_CONTENT_TOL_PX. Measured on the 7 covers it removes the inversion where two APPROVED
# covers ranked below two work-in-progress ones. Reported ALONGSIDE for now — the Score
# still uses the pointwise value until the weights are recalibrated against the eye.
# OPT-IN: it costs 0.2–1.0s per compare and the Score does not use it yet, so leaving it on
# would burn tens of seconds per cover in the gate's hot loop for a number nobody reads.
# Turn it on for metric-calibration work: set SWISS_TOL_METRIC=1 (or the constant, in-process).
_CONTENT_TOL_PX  = 2 if os.environ.get("SWISS_TOL_METRIC") else 0

# Text-aware metric (Fase 5): content_match is nearly BLIND to thin type (capa2 = 0.03
# even when it looks fine) because a 1px stroke offset zeroes the exact-pixel match. The
# text gate for the VLM measures ink OVERLAP inside the OCR boxes, TOLERANT of small
# misalignment (dilate both masks first), so a correct, well-placed string scores high
# even a pixel or two off. Measures the RENDERING of text; the STRING's correctness is
# the VLM's contained bit of trust (grounding + audit), not this metric.
_TEXT_INK_DIST  = 55     # pixel this far from the box's local background = ink
_TEXT_DILATE_PX = 3      # misalignment tolerance (px) — dilate ink before matching


def _content_metrics(orig: "np.ndarray", result: "np.ndarray") -> "tuple[float, float, float]":
    """
    Score only where the content is, so a big matching background can't inflate it.

    content_match : of every content pixel (non-background in EITHER image), the
                    fraction where the render's colour matches the original's.
    content_iou   : overlap of the two content masks (did we put content where the
                    original has content?) — catches missing/extra elements.

    A cover that reproduces its background but drops half its circles/text scores
    high on SSIM yet low here — which is the point.
    """
    import numpy as np  # noqa: PLC0415

    o = orig.astype(int)
    r = result.astype(int)
    bg = _background_color(orig)

    fg_o = np.sqrt(((o - bg) ** 2).sum(2)) > _CONTENT_BG_DIST
    fg_r = np.sqrt(((r - bg) ** 2).sum(2)) > _CONTENT_BG_DIST
    fg   = fg_o | fg_r
    if fg.sum() == 0:
        return 1.0, 1.0

    match = float(np.mean(np.sqrt(((o[fg] - r[fg]) ** 2).sum(1)) < _CONTENT_MATCH_D))
    union = (fg_o | fg_r).sum()
    iou   = float((fg_o & fg_r).sum() / union) if union else 1.0

    # Misalignment-tolerant variant: matched if the render carries this colour anywhere in a
    # small neighbourhood. Evaluated only on the content pixels, so it costs one pass per
    # shift over |fg| rather than over the whole frame.
    k = _CONTENT_TOL_PX
    if k <= 0:                                   # opt-in; identical to `match` when off
        return match, iou, match
    ofg = o[fg]
    matched = np.sqrt(((ofg - r[fg]) ** 2).sum(1)) < _CONTENT_MATCH_D
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            if dx == 0 and dy == 0:
                continue
            if matched.all():
                break
            rs = np.roll(np.roll(r, dy, axis=0), dx, axis=1)
            matched |= np.sqrt(((ofg - rs[fg]) ** 2).sum(1)) < _CONTENT_MATCH_D
    match_tol = float(matched.mean())
    return match, iou, match_tol


def residual_blobs(
    orig_path, result_path, canvas: dict, top: int = 6,
    dist: int = 70, min_area_frac: float = 0.0008,
) -> list:
    """Where does the render DISAGREE with the original, as ranked contiguous blobs?

    This is the system's own eye on its own output. Until now a human read the diff map,
    decided what each smudge was, and wrote a detector — that is the manual loop. Handing
    the ranked blobs to the VLM turns "the dev notices" into "the system notices".

    Returns, worst first: {bbox_cm, area_px, area_pct, orig_hex, render_hex}.
    """
    import numpy as np                    # noqa: PLC0415
    from PIL import Image                 # noqa: PLC0415
    from scipy import ndimage             # noqa: PLC0415

    o_img = Image.open(orig_path).convert("RGB")
    r_img = Image.open(result_path).convert("RGB").resize(o_img.size, Image.LANCZOS)
    O, R = np.asarray(o_img).astype(int), np.asarray(r_img).astype(int)
    h_px, w_px = O.shape[:2]
    W = canvas.get("width_cm", 21.0); H = canvas.get("height_cm", 29.7)

    bad = np.sqrt(((O - R) ** 2).sum(2)) > dist
    # open it up so anti-alias fringes along every edge don't register as "a blob"
    bad = ndimage.binary_opening(bad, np.ones((5, 5)))
    lbl, k = ndimage.label(bad)
    if not k:
        return []
    sizes = ndimage.sum(bad, lbl, range(1, k + 1))
    out = []
    for idx in np.argsort(-sizes)[:top]:
        n_px = int(sizes[idx])
        if n_px < min_area_frac * h_px * w_px:
            break
        m = lbl == int(idx) + 1
        ys, xs = np.where(m)
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
        co = O[m].mean(0).round().astype(int)
        cr = R[m].mean(0).round().astype(int)
        out.append({
            "bbox_cm": {"x": round(x0 / w_px * W, 2),
                        "y": round((h_px - y1) / h_px * H, 2),
                        "w": round((x1 - x0 + 1) / w_px * W, 2),
                        "h": round((y1 - y0 + 1) / h_px * H, 2)},
            "area_px": n_px,
            "area_pct": round(100.0 * n_px / (h_px * w_px), 2),
            "orig_hex": "#{:02X}{:02X}{:02X}".format(*co),
            "render_hex": "#{:02X}{:02X}{:02X}".format(*cr),
        })
    return out


def _background_color(arr: "np.ndarray") -> "np.ndarray":
    """Most common colour (quantised) = the background."""
    import numpy as np  # noqa: PLC0415
    q = (arr // 16).reshape(-1, 3)
    vals, counts = np.unique(q, axis=0, return_counts=True)
    return vals[counts.argmax()] * 16 + 8


def _content_split(
    orig: "np.ndarray", result: "np.ndarray",
    text_boxes_px: "list[tuple[int,int,int,int]]",
) -> "tuple[float | None, float]":
    """Split the content pixels into TYPE and everything else.

    `content_match` compares pixel to pixel. That is the right test for a flat shape and the
    wrong one for type: a glyph is nearly all edge, so a sub-pixel offset zeroes it even when
    the words, the size and the position are right — capa2 renders its text correctly and
    still scores 0.157. `text_match` already measures type properly (0.82 on the same cover)
    and carried NO weight in the Score.

    Returns the strict match over NON-text content, plus what share of the content is type,
    so the caller can score the type part with the tolerant metric and the rest strictly.
    Weighting is by share of CONTENT, never of the page: capa2's text boxes cover 2% of the
    page while being essentially the whole design, so page-area weighting would miss exactly
    the cover that needs this.
    """
    import numpy as np  # noqa: PLC0415

    o, r = orig.astype(int), result.astype(int)
    bg   = _background_color(orig)
    fg = ((np.sqrt(((o - bg) ** 2).sum(2)) > _CONTENT_BG_DIST)
          | (np.sqrt(((r - bg) ** 2).sum(2)) > _CONTENT_BG_DIST))
    n_fg = int(fg.sum())
    if not n_fg:
        return None, 0.0

    H, W = fg.shape
    txt = np.zeros(fg.shape, bool)
    for (x0, y0, x1, y1) in text_boxes_px or []:
        txt[max(0, y0):min(H, y1), max(0, x0):min(W, x1)] = True

    share = float((fg & txt).sum()) / n_fg
    rest  = fg & ~txt
    if not rest.any():                       # the whole design is type
        return None, share
    m = float(np.mean(np.sqrt(((o[rest] - r[rest]) ** 2).sum(1)) < _CONTENT_MATCH_D))
    return m, share


def _text_boxes_from_analysis(
    analysis: "dict | None", w_cm: float, h_cm: float, shape: tuple, pad: int = 3,
) -> "list[tuple[int,int,int,int]]":
    """OCR bbox_cm (TikZ y-up) → image pixel boxes (x0,y0,x1,y1), padded a little."""
    if not analysis:
        return []
    H, W = shape[0], shape[1]
    boxes = []
    for t in analysis.get("text_elements", []):
        b = t.get("bbox_cm")
        if not b:
            continue
        x0 = int(b["x"] / w_cm * W) - pad
        x1 = int((b["x"] + b["w"]) / w_cm * W) + pad
        y0 = int(H - (b["y"] + b["h"]) / h_cm * H) - pad
        y1 = int(H - b["y"] / h_cm * H) + pad
        boxes.append((x0, y0, x1, y1))
    return boxes


def text_match(
    orig: "np.ndarray", result: "np.ndarray",
    text_boxes_px: "list[tuple[int,int,int,int]]",
    ink_dist: int = _TEXT_INK_DIST, dilate: int = _TEXT_DILATE_PX,
) -> "float | None":
    """Misalignment-tolerant ink overlap inside the OCR text boxes (the Fase-5 text gate).

    Per box: ink = pixels far from that box's LOCAL background (handles white-on-dark and
    dark-on-light alike). Dilate both the original and rendered ink by `dilate` px, then:
      recall    = original ink that has rendered ink within tolerance
      precision = rendered ink that has original ink within tolerance
    Return their F1 (harmonic mean), aggregated over all boxes by ink count. Missing text
    → recall 0; phantom/extra text → precision 0; right shape, ~right place → high. Returns
    None when there are no text boxes (metric not applicable). Reuses _background_color and
    the same ink threshold family as content_match, so it's the same metric authority.
    """
    import numpy as np  # noqa: PLC0415
    from scipy.ndimage import binary_dilation  # noqa: PLC0415

    if not text_boxes_px:
        return None

    o, r = orig.astype(int), result.astype(int)
    H, W = o.shape[:2]
    rec_n = rec_d = prec_n = prec_d = 0
    for (x0, y0, x1, y1) in text_boxes_px:
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(W, x1), min(H, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        ob, rb = o[y0:y1, x0:x1], r[y0:y1, x0:x1]
        bg     = _background_color(orig[y0:y1, x0:x1])
        ink_o  = np.sqrt(((ob - bg) ** 2).sum(2)) > ink_dist
        ink_r  = np.sqrt(((rb - bg) ** 2).sum(2)) > ink_dist
        dil_o  = binary_dilation(ink_o, iterations=dilate)
        dil_r  = binary_dilation(ink_r, iterations=dilate)
        rec_n += int((ink_o & dil_r).sum()); rec_d += int(ink_o.sum())
        prec_n += int((ink_r & dil_o).sum()); prec_d += int(ink_r.sum())

    recall = rec_n / rec_d if rec_d else 1.0
    prec   = prec_n / prec_d if prec_d else 1.0
    return 0.0 if (prec + recall) == 0 else 2 * prec * recall / (prec + recall)



def structural_match(orig, result) -> float:
    """How much of the ORIGINAL's shape mass the render reproduces, matched as SHAPES.

    Blobs on both sides are matched one-to-one (Hungarian) on colour, area and centroid, so a
    shape a couple of pixels off still matches and the sub-pixel penalty that punishes every
    curve and every thin stroke disappears. Swapping figure and ground leaves nothing to
    match — the failure the pointwise metric waved through at 0.762.

    76.4% pairwise concordance with the user's labels on its own; it lifts SSIM 80.5% -> 82.9%.
    """
    import numpy as np
    from scipy import ndimage
    from scipy.optimize import linear_sum_assignment

    o, r = np.asarray(orig), np.asarray(result)

    def _pal(a, k=8):
        q = (a // 32).reshape(-1, 3)
        uq, cnt = np.unique(q, axis=0, return_counts=True)
        return (uq[np.argsort(-cnt)[:k]] * 32 + 16).astype(np.float32)

    def _comps(a, pal, min_frac=0.0006):
        h, w = a.shape[:2]
        idx = np.argmin(((a[:, :, None, :].astype(np.float32) - pal[None, None]) ** 2).sum(3), 2)
        out = []
        for ci in range(len(pal)):
            lab, _n = ndimage.label(idx == ci)
            for k, sl in enumerate(ndimage.find_objects(lab), start=1):
                if sl is None:
                    continue
                m = (lab[sl] == k)
                ar = int(m.sum())
                if ar < min_frac * w * h:
                    continue
                ys, xs = np.nonzero(m)
                out.append((ci, ar / (w * h),
                            (sl[0].start + ys.mean()) / h, (sl[1].start + xs.mean()) / w))
        return out

    pal = _pal(o)
    A, B = _comps(o, pal), _comps(r, pal)
    if not A:
        return 1.0 if not B else 0.0
    if not B:
        return 0.0
    C = np.full((len(A), len(B)), 10.0, np.float32)
    for i, (ci, ai, yi, xi) in enumerate(A):
        for j, (cj, aj, yj, xj) in enumerate(B):
            if ci == cj:
                C[i, j] = float(np.hypot(yi - yj, xi - xj)) + (1.0 - min(ai, aj) / max(ai, aj))
    ri, cj = linear_sum_assignment(C)
    got = sum(min(A[i][1], B[j][1]) * max(0.0, 1.0 - C[i, j])
              for i, j in zip(ri, cj) if C[i, j] < 10.0)
    return float(got / sum(a[1] for a in A))


def _text_box_f1(orig, result, box, ink_dist=_TEXT_INK_DIST, dilate=_TEXT_DILATE_PX) -> float:
    """The misalignment-tolerant ink F1 for ONE box (so a text.add can be judged on its
    OWN box, not the diluted mean over all boxes)."""
    import numpy as np  # noqa: PLC0415
    from scipy.ndimage import binary_dilation  # noqa: PLC0415
    H, W = orig.shape[:2]
    x0, y0, x1, y1 = max(0, box[0]), max(0, box[1]), min(W, box[2]), min(H, box[3])
    if x1 <= x0 or y1 <= y0:
        return 1.0
    ob, rb = orig[y0:y1, x0:x1].astype(int), result[y0:y1, x0:x1].astype(int)
    bg     = _background_color(orig[y0:y1, x0:x1])
    ink_o  = np.sqrt(((ob - bg) ** 2).sum(2)) > ink_dist
    ink_r  = np.sqrt(((rb - bg) ** 2).sum(2)) > ink_dist
    dil_o, dil_r = binary_dilation(ink_o, iterations=dilate), binary_dilation(ink_r, iterations=dilate)
    rec  = (ink_o & dil_r).sum() / ink_o.sum() if ink_o.sum() else 1.0
    prec = (ink_r & dil_o).sum() / ink_r.sum() if ink_r.sum() else 1.0
    return 0.0 if (prec + rec) == 0 else float(2 * prec * rec / (prec + rec))


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
