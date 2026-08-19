#!/usr/bin/env python3
"""
structural_reader.py — ONE generic reader, in place of one detector per shape.

The detector stack answers "is there a grid / a lattice / a mosaic here?" with a different
guess per shape, each tuned until the seven original covers stopped regressing. Adding twelve
covers showed what that costs: capa13 is a plain grid of squares and it collapsed; capa18 is a
triangle mosaic and the mosaic detector never fired.

This module does the same job by MEASURING instead of guessing:

    quantise to the measured palette
      → connected components per colour   (that IS the tiling, whatever shape it is)
      → for each component, pick the primitive that best EXPLAINS its pixels (IoU),
        trying rectangle / circle / ellipse / traced polygon
      → split a component that no single primitive explains, and keep the split only
        when the pieces explain it better

Nothing here knows what a grid or a mosaic is. Periodicity, symmetry and rhythm fall out of
the components themselves, which is what "feature, not detector" meant in the first place.

Two things the pixels alone get wrong, both handled:
  · TEXT — letterforms are ink like any other, so they get traced as little polygons and
    then the OCR draws the same words on top. The OCR already knows where text is; those
    boxes are masked out before tracing.
  · TOUCHING SHAPES — capa11's white circles touch, so they arrive as one blob. That is
    exactly the case the split step is for.

Public API:
    read(image_path, analysis) -> list[region] | None
"""

import numpy as np
from PIL import Image

try:
    import cv2
    from scipy import ndimage
    _CV = True
except ImportError:                                   # pragma: no cover
    _CV = False

# A colour must cover this much of the page to be worth tracing. Below it we are chasing
# antialias fringes and JPEG mush, not design.
_MIN_COVERAGE = 0.002
# A piece smaller than this fraction of the page is a speck.
_MIN_AREA_FRAC = 0.0006
# Below this IoU no single primitive explains the component, so try splitting it.
_SPLIT_MIN = 0.90
# A split is kept only if it explains this much more of the blob than the single shape did.
_SPLIT_GAIN = 0.04
# Runaway guard: a photographic or heavily dithered image can shatter into thousands of
# components. Past this we are transcribing noise, and the reader declines the cover.
_MAX_PIECES = 600
# OCR boxes are grown by this much before masking; the last glyph's antialias edge sits
# just outside the reported box (same reason cover_assembler pads by 4px).
_TEXT_PAD_PX = 5


def _hex_to_rgb(h: str) -> "tuple[int, int, int]":
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    u = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum()) / float(u) if u else 0.0


def _text_mask(analysis: dict, w: int, h: int, sx: float, sy: float, H: float) -> np.ndarray:
    """Pixels the OCR claims are type. bbox_cm is y-UP, the image is y-down."""
    m = np.zeros((h, w), bool)
    for el in analysis.get("text_elements", []):
        b = el.get("bbox_cm") or {}
        if not b:
            continue
        x0 = int(b.get("x", 0) / sx) - _TEXT_PAD_PX
        y0 = int((H - b.get("y", 0) - b.get("h", 0)) / sy) - _TEXT_PAD_PX
        x1 = int((b.get("x", 0) + b.get("w", 0)) / sx) + _TEXT_PAD_PX
        y1 = int((H - b.get("y", 0)) / sy) + _TEXT_PAD_PX
        m[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = True
    return m


# TRIED AND REVERTED (2026-08-17): filling a colour's holes when another colour occupies
# them, so capa10's orange rings would become solid bars with the red core repainting on
# top. It did NOT reach capa10 — those bars arrive as separate side strips, never a closed
# ring, so there is no hole to fill — and it cost capa16 (0.879→0.870) and capa18
# (0.682→0.662), where filling merged pieces that belong apart. capa10's scalloped bars are
# still open; the fix has to join the strips, not close a hole.


def _rrect(bh: int, bw: int, r: float) -> np.ndarray:
    """Mask of a rectangle with corner radius r — the standard rounded-box distance test:
    a pixel is outside only when it sits past BOTH edges of a corner, beyond the arc."""
    yy, xx = np.mgrid[0:bh, 0:bw]
    dx = np.maximum(0.0, np.maximum(r - xx, xx - (bw - 1 - r)))
    dy = np.maximum(0.0, np.maximum(r - yy, yy - (bh - 1 - r)))
    return (dx * dx + dy * dy) <= r * r


def _best_primitive(m: np.ndarray) -> "tuple[dict, float]":
    """Which primitive explains this blob? Rasterise each candidate and measure IoU.

    Measuring beats the fill-ratio signature it replaces: a fill near 0.5 could be a
    triangle or a half-moon, and 0.785 could be a circle or a rounded square. Drawing the
    candidate and comparing settles it, and the winner's own IoU is the confidence.
    """
    bh, bw = m.shape
    cands: "list[tuple[float, dict]]" = []

    rect = np.ones_like(m)
    cands.append((_iou(m, rect), {"shape_type": "rectangle"}))

    # A bar with rounded ends traced as a free polygon comes out scalloped (capa10's hot
    # dogs). Try a few corner radii and let the IoU pick; r = half the short side is a
    # stadium. Ties fall back to the plain rectangle, which is listed first.
    short = min(bh, bw)
    for frac in (0.25, 0.5, 0.75, 1.0):
        r = frac * short / 2.0
        if r < 1.5:
            continue
        cands.append((_iou(m, _rrect(bh, bw, r)),
                      {"shape_type": "rounded_rect", "_radius_px": r}))

    ell = np.zeros_like(m, np.uint8)
    cv2.ellipse(ell, ((bw - 1) // 2, (bh - 1) // 2),
                (max(bw // 2, 1), max(bh // 2, 1)), 0, 0, 360, 1, -1)
    ell = ell.astype(bool)
    # a circle is the special case of the ellipse, and the cheaper primitive when it fits
    if 0.85 < bw / float(bh) < 1.18:
        cands.append((_iou(m, ell), {"shape_type": "circle"}))
    else:
        cands.append((_iou(m, ell), {"shape_type": "ellipse"}))

    cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts:
        big = max(cnts, key=cv2.contourArea)
        for eps in (0.02, 0.01, 0.005):
            ap = cv2.approxPolyDP(big, eps * cv2.arcLength(big, True), True).reshape(-1, 2)
            if not (3 <= len(ap) <= 12):
                continue
            ras = np.zeros_like(m, np.uint8)
            cv2.fillPoly(ras, [ap.astype(np.int32)], 1)
            kind = "triangle" if len(ap) == 3 else "polygon"
            cands.append((_iou(m, ras.astype(bool)), {"shape_type": kind, "_pts_px": ap}))

    score, best = max(cands, key=lambda t: t[0])
    return best, score


def _split(m: np.ndarray) -> "list[np.ndarray]":
    """Cut a blob of touching shapes apart at its narrow waists (distance transform +
    watershed). Returns [] when it does not separate into more than one piece."""
    d = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 5)
    if d.max() < 3:
        return []
    peaks = d > 0.62 * d.max()
    seeds, n = ndimage.label(peaks)
    if n < 2:
        return []
    # watershed fills the pixels marked 0; outside the blob is a known background label,
    # each distance peak is its own label, and the rest of the blob is what gets assigned
    markers = np.zeros(m.shape, np.int32)
    markers[~m] = 1
    markers[seeds > 0] = seeds[seeds > 0] + 1
    lab = cv2.watershed(np.dstack([m.astype(np.uint8) * 255] * 3), markers)
    out = []
    for k in range(2, n + 2):
        piece = (lab == k) & m
        if piece.sum() > 20:
            out.append(piece)
    return out if len(out) > 1 else []


def read(image_path, analysis: dict) -> "list | None":
    """Read the cover's shapes straight from its pixels. Returns regions, or None when the
    image does not decompose into a sane number of pieces (the caller keeps the detectors)."""
    if not _CV:
        return None
    colors = [c for c in analysis.get("colors", [])
              if isinstance(c, dict) and c.get("coverage", 0) >= _MIN_COVERAGE]
    if len(colors) < 2:
        return None

    W = analysis["canvas"]["width_cm"]
    H = analysis["canvas"]["height_cm"]
    a = np.asarray(Image.open(image_path).convert("RGB")).astype(np.float32)
    h, w = a.shape[:2]
    sx, sy = W / w, H / h
    min_area = _MIN_AREA_FRAC * w * h

    pal = np.array([_hex_to_rgb(c["hex"]) for c in colors], np.float32)
    idx = np.argmin(((a[:, :, None, :] - pal[None, None]) ** 2).sum(3), 2)

    bgi = int(np.bincount(idx.ravel(), minlength=len(pal)).argmax())
    txt = _text_mask(analysis, w, h, sx, sy, H)
    idx[txt] = bgi                                     # let the OCR own the type

    regions = [{"id": "bg", "shape_type": "rectangle", "color_hex": colors[bgi]["hex"],
                "source": "reader",
                "bbox_cm": {"x": 0.0, "y": 0.0, "w": round(W, 3), "h": round(H, 3)}}]

    pieces: "list[tuple[int, dict]]" = []
    for ci in range(len(pal)):
        if ci == bgi:
            continue
        lab, _n = ndimage.label(idx == ci)
        for k, sl in enumerate(ndimage.find_objects(lab), start=1):
            if sl is None:
                continue
            m = (lab[sl] == k)
            if m.sum() < min_area or m.shape[0] < 4 or m.shape[1] < 4:
                continue
            blobs = [(m, sl)]
            best, sc = _best_primitive(m)
            if sc < _SPLIT_MIN:
                parts = _split(m)
                if parts:
                    # keep the split only when the pieces really explain the blob better
                    tot = sum(p.sum() for p in parts)
                    gain = sum(_best_primitive(_crop(p)[0])[1] * p.sum() for p in parts) / max(tot, 1)
                    if gain > sc + _SPLIT_GAIN:
                        blobs = [(_crop(p)[0], _offset(sl, _crop(p)[1])) for p in parts]
            for pm, psl in blobs:
                if pm.sum() < min_area:
                    continue
                shp, _s = _best_primitive(pm)
                pieces.append((int(pm.sum()),
                               _region(shp, psl, pm.shape, colors[ci]["hex"], sx, sy, H)))

    if not pieces or len(pieces) > _MAX_PIECES:
        return None
    pieces.sort(key=lambda t: -t[0])                   # big first; small ones paint on top
    regions += [p for _, p in pieces]
    return regions


def _crop(p: np.ndarray) -> "tuple[np.ndarray, tuple]":
    ys, xs = np.where(p)
    sl = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
    return p[sl], sl


def _offset(outer: tuple, inner: tuple) -> tuple:
    return (slice(outer[0].start + inner[0].start, outer[0].start + inner[0].stop),
            slice(outer[1].start + inner[1].start, outer[1].start + inner[1].stop))


def _region(shp: dict, sl: tuple, shape_px: tuple, hex_: str,
            sx: float, sy: float, H: float) -> dict:
    ys, xs = sl
    bh, bw = shape_px
    r = {"id": f"rd{xs.start}_{ys.start}", "shape_type": shp["shape_type"],
         "color_hex": hex_, "source": "reader",
         "bbox_cm": {"x": round(xs.start * sx, 3),
                     "y": round(H - (ys.start + bh) * sy, 3),
                     "w": round(bw * sx, 3), "h": round(bh * sy, 3)}}
    pts = shp.get("_pts_px")
    if pts is not None:
        r["points_cm"] = [[round((xs.start + px) * sx, 3), round(H - (ys.start + py) * sy, 3)]
                          for px, py in pts]
    if "_radius_px" in shp:
        r["radius_cm"] = round(shp["_radius_px"] * sx, 3)
    return r
