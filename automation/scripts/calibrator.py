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
# Ink search window around an element's expected box, in cm. Horizontal is
# generous (width error can be large); vertical is TIGHT because cover text
# lines sit only ~0.2cm apart — a wider window would swallow the neighbouring
# line and produce nonsense (a full line-height of spurious dy, a doubled height).
_MARGIN_X_CM = 0.25
_MARGIN_Y_CM = 0.10

# A pixel counts as ink when it differs from the window's background by more than
# this RGB distance. The background is the window's median (text is the minority).
_INK_RGB_DIST = 60.0

# Apply only this fraction of each measured error per pass. Under-correcting is
# deliberate: it damps the scale⇄position coupling so the loop converges instead
# of oscillating, and a single bad measurement can never yank an element far.
_DAMP = 0.8

# Ignore corrections below this — they are measurement noise, not real error.
_MIN_SHIFT_CM  = 0.015   # ≈0.5px at the reference 86 dpi
_MIN_SCALE_ADJ = 0.008   # 0.8%

# Never let the accumulated correction swing a value past these guards.
_MAX_SHIFT_CM  = 0.60
_MAX_SCALE     = (0.60, 1.40)


def calibrate(
    analysis:      dict,
    original_path: "str | Path",
    render_path:   "str | Path",
) -> "tuple[dict, int]":
    """
    Calibrate every text element by measuring the render against the original.

    For each element the SAME ink measurement runs on both images inside the
    same window, so any systematic bias cancels and the difference is the real
    error. That error is folded (damped) into per-element hscale/dx_cm/dy_cm,
    which tikz_generator applies on the next pass.

    Parameters
    ----------
    analysis      : cover_analysis dict; text_elements carry bbox_cm (used only
                    to locate each element's search window)
    original_path : the reference cover image (ground truth)
    render_path   : PNG of the compiled PDF from the current pass

    Returns
    -------
    (new_analysis, n_changed) — deep copy with corrections updated, and how many
    elements moved. n_changed == 0 means converged.
    """
    import numpy as np                 # noqa: PLC0415
    from PIL import Image              # noqa: PLC0415

    doc   = copy.deepcopy(analysis)
    texts = doc.get("text_elements", [])
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
        want = _measure_ink(orig, el, W_cm, H_cm, w_px, h_px)   # original (target)
        got  = _measure_ink(rend, el, W_cm, H_cm, w_px, h_px)   # this render
        if want is None or got is None:
            continue
        if _apply_correction(el, want, got):
            n_changed += 1

    return doc, n_changed


# ─── Measurement ──────────────────────────────────────────────────────────────

def _measure_ink(
    img:   "np.ndarray",
    el:    dict,
    W_cm:  float,
    H_cm:  float,
    w_px:  int,
    h_px:  int,
) -> "dict | None":
    """
    Measure the tight ink box of one element inside its window in `img`.

    Returns {x, y, w, h} in cm (TikZ orientation, y = ink bottom) or None when
    the window holds no ink.
    """
    import numpy as np  # noqa: PLC0415

    b = el.get("bbox_cm", {})
    if not b or b.get("w", 0) <= 0 or b.get("h", 0) <= 0:
        return None

    x0 = max(0.0,  b["x"] - _MARGIN_X_CM)
    x1 = min(W_cm, b["x"] + b["w"] + _MARGIN_X_CM)
    y0 = max(0.0,  b["y"] - _MARGIN_Y_CM)
    y1 = min(H_cm, b["y"] + b["h"] + _MARGIN_Y_CM)

    c0 = int(x0 / W_cm * w_px)
    c1 = int(x1 / W_cm * w_px)
    r0 = int((H_cm - y1) / H_cm * h_px)   # TikZ y → image row (y grows up)
    r1 = int((H_cm - y0) / H_cm * h_px)
    if c1 <= c0 or r1 <= r0:
        return None

    win = img[r0:r1, c0:c1].astype(int)
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

def _apply_correction(el: dict, want: dict, got: dict) -> bool:
    """
    Fold the measured error (want − got) into hscale/dx_cm/dy_cm, damped.
    Returns True when anything changed by more than the noise floor.
    """
    changed = False

    # ── Width → horizontal scale ──────────────────────────────────────────────
    if got["w"] > 1e-6:
        ratio = want["w"] / got["w"]
        if abs(ratio - 1.0) > _MIN_SCALE_ADJ:
            cur   = el.get("hscale", 1.0)
            new_s = cur * (1.0 + _DAMP * (ratio - 1.0))
            new_s = min(max(new_s, _MAX_SCALE[0]), _MAX_SCALE[1])
            if abs(new_s - cur) > 1e-6:
                el["hscale"] = round(new_s, 4)
                changed = True

    # ── Left edge → x shift ───────────────────────────────────────────────────
    dx = want["x"] - got["x"]
    if abs(dx) > _MIN_SHIFT_CM:
        new_dx = _clamp(el.get("dx_cm", 0.0) + _DAMP * dx, _MAX_SHIFT_CM)
        el["dx_cm"] = round(new_dx, 4)
        changed = True

    # ── Ink bottom → y shift ──────────────────────────────────────────────────
    dy = want["y"] - got["y"]
    if abs(dy) > _MIN_SHIFT_CM:
        new_dy = _clamp(el.get("dy_cm", 0.0) + _DAMP * dy, _MAX_SHIFT_CM)
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
