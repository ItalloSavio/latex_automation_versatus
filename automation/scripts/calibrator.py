#!/usr/bin/env python3
"""
calibrator.py — Closed-loop calibration of text elements against the render.

The generator has to guess how wide its font renders compared to the original's
type (Swiss covers set Helvetica with tight tracking; the available render font
is never an exact match). That guess used to be one global magic number.

This module removes the guess: it renders, MEASURES the ink each text element
actually produced, compares it to the ink measured from the original image, and
writes a per-element correction back into the analysis:

    hscale  float — horizontal scale so the rendered ink matches the original's width
    dx_cm   float — additive x shift so the ink left edges line up
    dy_cm   float — additive y shift so the ink baselines line up

tikz_generator applies these on the next pass. Because every value comes from a
measurement rather than a constant, it self-adapts to any font or cover.

Public API:
    calibrate(analysis, original_path, render_path) -> (new_analysis, n_changed)
"""

import copy
from pathlib import Path

# Ink search window around an element's expected box, in cm. Wide enough to find
# a mis-rendered element, tight enough not to catch its neighbour (text elements
# on a cover sit ≥0.5cm apart).
_SEARCH_MARGIN_CM = 0.30

# A pixel counts as ink when it differs from the window's background by more than
# this RGB distance. The background is the window's median (text is the minority).
_INK_RGB_DIST = 60.0

# Ignore corrections below this — they are measurement noise, not real error.
_MIN_SHIFT_CM  = 0.015   # ≈0.5px at the reference 86 dpi
_MIN_SCALE_ADJ = 0.005   # 0.5%

# Never let one pass swing a value further than this (guards against a bad match).
_MAX_SHIFT_CM  = 0.60
_MAX_SCALE     = (0.60, 1.40)


def calibrate(
    analysis:      dict,
    original_path: "str | Path",
    render_path:   "str | Path",
) -> "tuple[dict, int]":
    """
    Measure each text element in the render and correct its scale/offset.

    Parameters
    ----------
    analysis      : cover_analysis dict (its text_elements carry the ORIGINAL ink
                    boxes measured by ocr_extractor — the ground truth)
    original_path : the reference cover image
    render_path   : PNG of the compiled PDF from the current pass

    Returns
    -------
    (new_analysis, n_changed) — a deep copy with hscale/dx_cm/dy_cm updated, and
    how many elements actually moved. n_changed == 0 means converged.
    """
    import numpy as np                 # noqa: PLC0415
    from PIL import Image              # noqa: PLC0415

    doc    = copy.deepcopy(analysis)
    texts  = doc.get("text_elements", [])
    if not texts:
        return doc, 0

    canvas = doc.get("canvas", {})
    W_cm   = canvas.get("width_cm",  21.0)
    H_cm   = canvas.get("height_cm", 29.7)

    orig = np.array(Image.open(original_path).convert("RGB"))
    h_px, w_px = orig.shape[:2]
    rend = np.array(
        Image.open(render_path).convert("RGB").resize((w_px, h_px), Image.LANCZOS)
    )

    n_changed = 0
    for el in texts:
        measured = _measure_element(rend, el, W_cm, H_cm, w_px, h_px)
        if measured is None:
            continue
        if _apply_correction(el, measured):
            n_changed += 1

    return doc, n_changed


# ─── Measurement ──────────────────────────────────────────────────────────────

def _measure_element(
    rend:  "np.ndarray",
    el:    dict,
    W_cm:  float,
    H_cm:  float,
    w_px:  int,
    h_px:  int,
) -> "dict | None":
    """
    Find the ink this element produced in the render.

    Returns {x, y, w, h} in cm (ink box, TikZ orientation) or None when the
    window holds no ink (element missing or search failed).
    """
    import numpy as np  # noqa: PLC0415

    b = el.get("bbox_cm", {})
    if not b or b.get("w", 0) <= 0 or b.get("h", 0) <= 0:
        return None

    m  = _SEARCH_MARGIN_CM
    x0 = max(0.0,  b["x"] - m)
    x1 = min(W_cm, b["x"] + b["w"] + m)
    y0 = max(0.0,  b["y"] - m)
    y1 = min(H_cm, b["y"] + b["h"] + m)

    c0 = int(x0 / W_cm * w_px)
    c1 = int(x1 / W_cm * w_px)
    r0 = int((H_cm - y1) / H_cm * h_px)   # TikZ y → image row (y grows up)
    r1 = int((H_cm - y0) / H_cm * h_px)
    if c1 <= c0 or r1 <= r0:
        return None

    win = rend[r0:r1, c0:c1].astype(int)
    if win.size == 0:
        return None

    # Background = window median (glyph strokes are the minority); ink = far from it.
    bg   = np.median(win.reshape(-1, 3), axis=0)
    dist = np.sqrt(((win - bg) ** 2).sum(axis=2))
    mask = dist > _INK_RGB_DIST

    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return None

    ink_r0, ink_r1 = int(rows[0]), int(rows[-1]) + 1
    ink_c0, ink_c1 = int(cols[0]), int(cols[-1]) + 1

    return {
        "x": (c0 + ink_c0) / w_px * W_cm,
        "y": (h_px - (r0 + ink_r1)) / h_px * H_cm,   # ink bottom
        "w": (ink_c1 - ink_c0) / w_px * W_cm,
        "h": (ink_r1 - ink_r0) / h_px * H_cm,
    }


# ─── Correction ───────────────────────────────────────────────────────────────

def _apply_correction(el: dict, got: dict) -> bool:
    """
    Fold the measured error into the element's hscale/dx_cm/dy_cm.
    Returns True when anything changed by more than the noise floor.
    """
    want = el["bbox_cm"]
    changed = False

    # ── Width → horizontal scale ──────────────────────────────────────────────
    if got["w"] > 1e-6:
        ratio = want["w"] / got["w"]
        if abs(ratio - 1.0) > _MIN_SCALE_ADJ:
            new_scale = el.get("hscale", 1.0) * ratio
            new_scale = min(max(new_scale, _MAX_SCALE[0]), _MAX_SCALE[1])
            if abs(new_scale - el.get("hscale", 1.0)) > 1e-6:
                el["hscale"] = round(new_scale, 4)
                changed = True

    # ── Left edge → x shift ───────────────────────────────────────────────────
    # Measured AFTER the scale correction lands, so only take the part of the gap
    # that a shift can fix: the left edge itself.
    dx = want["x"] - got["x"]
    if abs(dx) > _MIN_SHIFT_CM:
        new_dx = _clamp(el.get("dx_cm", 0.0) + dx, _MAX_SHIFT_CM)
        el["dx_cm"] = round(new_dx, 4)
        changed = True

    # ── Ink bottom → y shift ──────────────────────────────────────────────────
    dy = want["y"] - got["y"]
    if abs(dy) > _MIN_SHIFT_CM:
        new_dy = _clamp(el.get("dy_cm", 0.0) + dy, _MAX_SHIFT_CM)
        el["dy_cm"] = round(new_dy, 4)
        changed = True

    return changed


def _clamp(v: float, limit: float) -> float:
    return min(max(v, -limit), limit)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    _usage = (
        f"Uso: python {Path(__file__).name} <analysis.json> <original> <render.png>\n\n"
        "Mede o render e imprime a correcao por elemento de texto (nao grava).\n\n"
        "Exemplo:\n"
        "  python calibrator.py automation/output/replicated/capa_teste4_analysis.json \\\n"
        "         capas_teste/capa_teste4.png \\\n"
        "         automation/output/replicated/capa_teste4_render.png"
    )

    if len(sys.argv) < 4 or sys.argv[1] in ("-h", "--help"):
        print(_usage)
        sys.exit(0)

    _analysis = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    _new, _n  = calibrate(_analysis, sys.argv[2], sys.argv[3])

    print(f"[CALIBRATE] {_n} elemento(s) ajustado(s)\n")
    for _el in _new.get("text_elements", []):
        if any(k in _el for k in ("hscale", "dx_cm", "dy_cm")):
            print(
                f"  {_el['text']!r:34s} "
                f"hscale={_el.get('hscale', 1.0):.4f}  "
                f"dx={_el.get('dx_cm', 0.0):+.3f}cm  "
                f"dy={_el.get('dy_cm', 0.0):+.3f}cm"
            )
