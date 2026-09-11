#!/usr/bin/env python3
"""
ocr_extractor.py — OCR text extraction with bounding boxes in centimeters.

Uses EasyOCR (pip install easyocr) to detect and recognize text in cover
images, then normalizes all coordinates to centimeters so downstream modules
(cover_assembler, tikz_generator) work in a single unit.

EasyOCR was chosen over PaddleOCR because it supports Python 3.12+ and
installs purely via pip (no binary system tools, no CUDA required when
gpu=False).

Public API:
    extract_text(image_path, width_cm=21.0, height_cm=29.7) -> list[dict]

Each returned dict:
    text          str    — recognized text string
    bbox_cm       dict   — tight ink {x, y, w, h} in cm; y from bottom-left (TikZ)
    baseline_y_cm float  — TikZ y of the text baseline (for base-anchored nodes)
    font_size_pt  float  — em size in points, from ink height + vertical metrics
    stroke_ratio  float  — stroke-width ÷ em proxy (weight cue for font_matcher)
    confidence    float  — OCR confidence in [0, 1]
    color_hex     str    — estimated foreground (text) color, e.g. "#FFFFFF"

Returns [] silently when EasyOCR / numpy / Pillow are not installed.
"""

from pathlib import Path

# Swiss-design covers use clean, high-contrast type, so genuine text lines
# reliably score ≥ 0.5 while noise scores far lower. 0.50 (vs the old 0.60)
# recovers real secondary lines that EasyOCR rates just under 0.60 — e.g. a
# date/time footer line at ~0.59 — without admitting spurious detections.
_MIN_CONFIDENCE = 0.50   # a reading at or above this is kept outright
# Below it, keep a reading only when it is LONG. Measured over the eight text-heavy covers,
# confidence alone does not separate real captions from noise, but confidence + LENGTH does:
# between 0.20 and 0.45 everything real is long ('brooklyn tne shirts' 0.40, 'september 12 13,
# 74, 1975' 0.28, '315 bowery' 0.24, 'Material tecnico de formacso' 0.30) and everything
# spurious is 1-3 characters ('9' 0.39, '222' 0.23, '8' 0.21). Under 0.20 the noise gets long
# again — capa14's rotated type produces 20-30 character gibberish at 0.00-0.04 — so the floor
# stays. This recovers 8 real captions and admits none of the junk.
_WEAK_CONFIDENCE = 0.20  # nothing under this, at any length
_WEAK_MIN_CHARS  = 8     # alphanumeric characters required between _WEAK_ and _MIN_
_MIN_HEIGHT_CM  = 0.15   # drop sub-millimeter boxes (sensor noise / artifacts)
_CM_TO_PT       = 28.35  # typographic conversion

# EasyOCR quads run taller and wider than the ink they enclose, so a font size
# taken from the quad height overshoots and text renders too big. We instead
# measure the actual dark-ink bounding box inside the quad and convert its
# height to an em using Helvetica/Arial vertical metrics:
#   ascender ≈ 0.735·em, descender ≈ 0.21·em.
# Text with a descender glyph spans ascender→descender (≈0.945·em); text without
# spans ascender→baseline (≈0.735·em).
_ASCENDER_RATIO   = 0.735   # ink top → baseline, as a fraction of em
_ASC_DESC_RATIO   = 0.945   # ink top → descender bottom, as a fraction of em
_DESCENDER_CHARS  = set("gjpqy")
_DESCENDER_RATIO  = 0.21    # baseline → descender bottom, as a fraction of em

# Weight: median horizontal dark-run length ÷ ink height ≈ stroke-width / em.
# Helvetica regular stems land near 0.10, bold near 0.15+; 0.125 separates them.
_BOLD_STROKE_RATIO = 0.125
_INK_LUMA_THRESH   = 100    # pixels darker than this (0–255 luma) count as ink


# ─── Public entry point ───────────────────────────────────────────────────────

def extract_text(
    image_path: "str | Path",
    width_cm:   float = 21.0,
    height_cm:  float = 29.7,
) -> "list[dict]":
    """
    Extract text elements from a cover image using PaddleOCR.

    Parameters
    ----------
    image_path : path to image (PNG / JPEG / WEBP)
    width_cm   : physical width in cm  (default: A4 portrait = 21 cm)
    height_cm  : physical height in cm (default: A4 portrait = 29.7 cm)

    Returns
    -------
    list of text-element dicts, sorted top-to-bottom then left-to-right.
    Empty list if PaddleOCR is unavailable or no text is found.
    """
    try:
        return _run_ocr(Path(image_path).resolve(), width_cm, height_cm)
    except Exception as exc:
        _s = str(exc)
        if "No module named" in _s or "ModuleNotFoundError" in type(exc).__name__:
            return []
        print(f"    [OCR] Aviso: extracao falhou ({type(exc).__name__}: {_s[:120]})")
        return []


# ─── Core OCR pipeline ────────────────────────────────────────────────────────

def _run_ocr(path: Path, width_cm: float, height_cm: float) -> "list[dict]":
    import easyocr          # noqa: PLC0415
    import numpy as np      # noqa: PLC0415
    from PIL import Image   # noqa: PLC0415

    img  = Image.open(path).convert("RGB")
    w_px = img.width
    h_px = img.height
    arr  = np.array(img)
    gray = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]

    # EasyOCR: gpu=False → CPU-only, no CUDA required.
    # ['en', 'pt'] covers both English and Portuguese text found on covers.
    # verbose=False suppresses download-progress and inference spam.
    # width_ths=0.8 (default 0.5) lets EasyOCR join fragments across a wider gap,
    # so a single line broken by a separator ("65p in advance / 75p at the door")
    # is read as one string with the "/" instead of two boxes that drop it.
    reader = easyocr.Reader(["en", "pt"], gpu=False, verbose=False)
    result = reader.readtext(str(path), width_ths=0.8)

    elements: list[dict] = []
    if not result:
        return elements

    # EasyOCR result format: [(quad, text, confidence), ...]
    for quad, text, conf in result:
        text = text.strip()
        if not text:
            continue
        if conf < _MIN_CONFIDENCE:
            n_alnum = sum(ch.isalnum() for ch in text)
            if conf < _WEAK_CONFIDENCE or n_alnum < _WEAK_MIN_CHARS:
                continue

        # Convert 4-corner quad to axis-aligned pixel bbox
        xs = [p[0] for p in quad]
        ys = [p[1] for p in quad]
        x1, y1 = int(min(xs)), int(min(ys))
        x2, y2 = int(max(xs)), int(max(ys))

        # Tighten the loose OCR quad to the actual ink it encloses. Everything
        # downstream (size, position, weight) keys off these ink pixels.
        ink = _measure_ink(gray[y1:y2, x1:x2])
        if ink is None:
            continue
        ix0, iy0, ix1, iy1, stroke_ratio = ink
        px0, py0, px1, py1 = x1 + ix0, y1 + iy0, x1 + ix1, y1 + iy1

        ink_h_px = py1 - py0
        h_box_cm = ink_h_px / h_px * height_cm
        if h_box_cm < _MIN_HEIGHT_CM:
            continue
        w_box_cm = (px1 - px0) / w_px * width_cm

        # Em height from ink height, accounting for whether a descender is present.
        has_desc = any(c in _DESCENDER_CHARS for c in text.lower())
        em_ratio = _ASC_DESC_RATIO if has_desc else _ASCENDER_RATIO
        em_px    = ink_h_px / em_ratio
        font_pt  = em_px / h_px * height_cm * _CM_TO_PT

        # Baseline sits a descender's depth above the ink bottom (or at it when
        # there is no descender). TikZ y grows upward from the bottom edge.
        desc_px     = (em_px * _DESCENDER_RATIO) if has_desc else 0.0
        baseline_px = py1 - desc_px
        x_cm        = px0 / w_px * width_cm
        y_cm        = (h_px - py1) / h_px * height_cm            # ink bottom
        baseline_cm = (h_px - baseline_px) / h_px * height_cm

        roi       = arr[py0:py1, px0:px1]
        color_hex = _estimate_text_color(roi)

        elements.append({
            "text":         text,
            "bbox_cm":      {
                "x": round(x_cm,     3),
                "y": round(y_cm,     3),
                "w": round(w_box_cm, 3),
                "h": round(h_box_cm, 3),
            },
            "baseline_y_cm": round(baseline_cm, 3),
            "font_size_pt":  round(font_pt, 1),
            "stroke_ratio":  round(stroke_ratio, 3),
            "confidence":    round(conf, 3),
            "color_hex":     color_hex,
        })

    # Sort top-to-bottom (descending TikZ y), then left-to-right
    elements.sort(key=lambda e: (-e["bbox_cm"]["y"], e["bbox_cm"]["x"]))
    return elements


# ─── Ink geometry ─────────────────────────────────────────────────────────────

def _measure_ink(gray_roi: "np.ndarray") -> "tuple[int,int,int,int,float] | None":
    """
    Find the tight dark-ink bounding box inside a (loose) OCR quad.

    Returns (x0, y0, x1, y1, stroke_ratio) in ROI-local pixel coordinates, where
    stroke_ratio = median horizontal dark-run length ÷ ink height (a scale-free
    proxy for stroke weight). Returns None when the ROI holds no ink.
    """
    import numpy as np  # noqa: PLC0415

    if gray_roi.size == 0:
        return None
    mask = gray_roi < _INK_LUMA_THRESH
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return None
    y0, y1 = int(rows[0]), int(rows[-1]) + 1
    x0, x1 = int(cols[0]), int(cols[-1]) + 1

    ink_h = max(y1 - y0, 1)
    runs  = _dark_run_lengths(mask[y0:y1, x0:x1])
    stroke_ratio = (float(np.median(runs)) / ink_h) if runs else 0.0
    return x0, y0, x1, y1, stroke_ratio


def _dark_run_lengths(mask: "np.ndarray") -> "list[int]":
    """Lengths of every horizontal run of True pixels (stroke-width samples)."""
    runs: list[int] = []
    for row in mask:
        count = 0
        for v in row:
            if v:
                count += 1
            elif count:
                runs.append(count)
                count = 0
        if count:
            runs.append(count)
    return runs


# ─── Text color estimation ────────────────────────────────────────────────────

def _estimate_text_color(roi: "np.ndarray") -> str:
    """
    Estimate the foreground (text) color from a cropped ink region.

    Strategy: 2-cluster K-means, then take the MINORITY cluster as the text.
    Within a tight ink box the glyph strokes always cover less area than the
    surrounding background, so the smaller cluster is the ink regardless of
    whether the text is dark-on-light or light-on-dark. (The old luminance
    heuristic misfired when the two cluster centres averaged near mid-grey,
    picking the background and washing near-black text out to a mid charcoal.)
    Falls back to #000000 when the region is too small or sklearn is absent.
    """
    try:
        import numpy as np                  # noqa: PLC0415
        from sklearn.cluster import KMeans  # noqa: PLC0415

        pixels = roi.reshape(-1, 3).astype(float)
        if len(pixels) < 10:
            return "#000000"

        km       = KMeans(n_clusters=2, n_init=3, random_state=0).fit(pixels)
        counts   = np.bincount(km.labels_, minlength=2)
        text_rgb = km.cluster_centers_[int(np.argmin(counts))]

        r = max(0, min(255, int(round(text_rgb[0]))))
        g = max(0, min(255, int(round(text_rgb[1]))))
        b = max(0, min(255, int(round(text_rgb[2]))))
        return f"#{r:02X}{g:02X}{b:02X}"

    except Exception:
        return "#000000"



# ─── Colour per span (A4) ─────────────────────────────────────────────────────

_SPAN_GAP_MIN  = 150.0   # RGB distance between the two halves' ink before we split at all
_SPAN_SIDE_MIN = 0.25    # each side must own this fraction of the inked columns
_SPAN_INK_MIN  = 60.0    # a pixel is ink when it is this far from ITS OWN column background
# A column whose "ink" fills the whole box is not ink — the per-column background estimate
# failed there. It fails exactly where the box ABUTS another region: capa8's "underground"
# sits right on top of the orange half-disc, so `bg` is the median of black-above and
# orange-below and comes out ORANGE, which makes the real black ground register as ink at
# full column height. The measured ink is then #000009 on those columns and #DFE1DE on the
# honest ones — a 240 RGB gap that clears _SPAN_GAP_MIN and splits a word whose ink is
# uniform (#DEE0D9..#DFE2DB across 8 column bands, under 2 points of luminance).
# This is the SAME failure the per-column sampling was introduced to avoid; it just moved
# from the whole box to the boundary columns.
# Measured separation on the four candidates: fraction of columns above 0.85 is
#   capa8 "underground" 62% (FALSE) · capa17 "SWISS" 25% · capa19 "theshining" 2% (TRUE).
_SPAN_INK_MAX_FRAC = 0.85
_SPAN_ROW_FRAC = 0.18   # share of the span a row must span to count as a line of type


def split_bicolour_text(elements: list, image_path, width_cm: float, height_cm: float) -> list:
    """Split one OCR element into two when its ink genuinely changes colour along x.

    EasyOCR hands back one box with one colour, so a title that crosses two regions gets a
    single ink colour and half of it goes invisible: capa19's "theshining" is light over the
    black shape and dark over the yellow, and painting it all #2B2A25 erases "the".

    The background is sampled PER COLUMN, from just above and below the box. That matters:
    a 2-cluster KMeans over the whole box separates the two BACKGROUNDS, not ink from
    background, so it is blind precisely here — an earlier attempt using it reported zero
    bicolour elements on the very covers that have them. Sampling one point under the centre
    fails for the same reason (capa17's "SWISS" has its centre in a black bar while the word
    lies on white), which is why that guard was reverted.

    Measured on the 20 covers: 3 of 140 elements clear both guards (capa8 "underground",
    capa17 "SWISS", capa19 "theshining") and the cut lands on the word boundary — 33% of
    "theshining" is exactly "the". The other 137 are returned untouched.
    """
    try:
        import numpy as np                 # noqa: PLC0415
        from PIL import Image              # noqa: PLC0415
    except Exception:
        return elements

    try:
        arr = np.asarray(Image.open(image_path).convert("RGB")).astype(float)
    except Exception:
        return elements
    h_px, w_px = arr.shape[:2]

    out = []
    for el in elements:
        split = _find_span_cut(arr, el, width_cm, height_cm, w_px, h_px)
        if split is None:
            out.append(el)
            continue
        frac, hex1, hex2 = split
        b = el["bbox_cm"]
        ncut = max(1, min(len(el["text"]) - 1, round(frac * len(el["text"]))))
        for text, x, w, hexc in (
            (el["text"][:ncut], b["x"],                 b["w"] * frac,       hex1),
            (el["text"][ncut:], b["x"] + b["w"] * frac, b["w"] * (1 - frac), hex2),
        ):
            part = dict(el)
            part["text"] = text
            part["bbox_cm"] = {"x": round(x, 3), "y": b["y"],
                               "w": round(w, 3), "h": b["h"]}
            part["color_hex"] = hexc
            out.append(part)
    return out


def _fit_span_metrics(part: dict, arr, width_cm: float, height_cm: float,
                      w_px: int, h_px: int) -> None:
    r"""MEASURED AND NOT USED — kept for the finding, not for the behaviour.

    Re-measure this span's SIZE and BASELINE from its own ink, in place.

    ⚠️ Wiring this in made capa19 WORSE (0.9185 -> 0.8708). The premise looked solid — the
    stored 135.5pt against ~85pt of real glyph — but the nominal size never reaches the page:
    `_build_text_nodes` already shrinks any line that would run off the canvas, and that cap
    lands near the right size on its own. Probing the element directly confirmed it, with
    nothing beating the status quo: 85pt regular -0.0068, 85pt bold -0.0006, 95pt bold
    -0.0015. Correcting a number that is corrected downstream just moves it away from the
    answer. Do not re-wire without first checking what the RENDER does, not the JSON.

    The colour was not the only thing the whole-box measurement got wrong. `_measure_ink`
    looks for dark ink across the entire OCR quad, and when the quad crosses a dark SHAPE the
    shape's edge is read as ink: capa19's title box came out 4.52cm tall against 2.85cm of
    real glyph, so the derived size was 135.5pt where the type is ~85pt — 59% too large, and
    the baseline landed low to match.

    Per column we already know the local background, so on the "the" columns the black form
    IS the background and only the white glyphs count. That is what makes an honest cap
    height available here and nowhere else.
    """
    import numpy as np  # noqa: PLC0415

    b = part["bbox_cm"]
    x0 = max(0, int(b["x"] / width_cm * w_px))
    x1 = min(w_px, int((b["x"] + b["w"]) / width_cm * w_px))
    y1 = min(h_px, int((height_cm - b["y"]) / height_cm * h_px))
    y0 = max(0, int(y1 - b["h"] / height_cm * h_px))
    if x1 - x0 < 6 or y1 - y0 < 6:
        return

    pad = max(2, int((y1 - y0) * 0.35))
    rows = np.zeros(y1 - y0, dtype=int)
    for x in range(x0, x1):
        ctx = [c for c in (arr[max(0, y0 - pad):y0, x], arr[y1:min(h_px, y1 + pad), x])
               if len(c)]
        if not ctx:
            continue
        bg = np.median(np.vstack(ctx), axis=0)
        col = arr[y0:y1, x]
        rows += (np.linalg.norm(col - bg, axis=1) > _SPAN_INK_MIN).astype(int)

    # A row of TYPE is lit across much of the span; a stray graphic feature is not. capa19
    # hides a small yellow arrow inside the black form, directly under "the" — against that
    # black ground it reads as ink and stretched the measured extent to 176pt for a word set
    # at about 85. Requiring a row to be lit across a fair share of the columns keeps glyphs
    # and drops the arrow.
    lit = np.where(rows >= max(2, int((x1 - x0) * _SPAN_ROW_FRAC)))[0]
    if len(lit) < 4:
        return
    ink_h_px = lit[-1] - lit[0] + 1
    if ink_h_px < 4 or ink_h_px > (y1 - y0):
        return

    has_desc = any(c in _DESCENDER_CHARS for c in part.get("text", "").lower())
    em_px = ink_h_px / (_ASC_DESC_RATIO if has_desc else _ASCENDER_RATIO)
    part["font_size_pt"] = round(em_px / h_px * height_cm * _CM_TO_PT, 1)

    desc_px = (em_px * _DESCENDER_RATIO) if has_desc else 0.0
    baseline_px = (y0 + lit[-1]) - desc_px
    part["baseline_y_cm"] = round((h_px - baseline_px) / h_px * height_cm, 3)
    part["bbox_cm"]["y"] = round((h_px - (y0 + lit[-1])) / h_px * height_cm, 3)
    part["bbox_cm"]["h"] = round(ink_h_px / h_px * height_cm, 3)


def _find_span_cut(arr, el, width_cm, height_cm, w_px, h_px):
    """Return (cut_fraction, left_hex, right_hex) when the ink is genuinely two-coloured."""
    import numpy as np  # noqa: PLC0415

    b = el.get("bbox_cm") or {}
    try:
        x0 = int(b["x"] / width_cm * w_px)
        x1 = int((b["x"] + b["w"]) / width_cm * w_px)
        y1 = int((height_cm - b["y"]) / height_cm * h_px)
        y0 = int(y1 - b["h"] / height_cm * h_px)
    except Exception:
        return None
    x0, x1 = max(0, x0), min(w_px, x1)
    y0, y1 = max(0, y0), min(h_px, y1)
    if x1 - x0 < 12 or y1 - y0 < 4:
        return None

    pad  = max(2, int((y1 - y0) * 0.35))
    cols = []
    for x in range(x0, x1):
        ctx = [c for c in (arr[max(0, y0 - pad):y0, x], arr[y1:min(h_px, y1 + pad), x]) if len(c)]
        if not ctx:
            continue
        bg  = np.median(np.vstack(ctx), axis=0)
        col = arr[y0:y1, x]
        d   = np.linalg.norm(col - bg, axis=1)
        ink = col[d > _SPAN_INK_MIN]
        # Ink that spans the full column height is a failed background estimate, not a
        # letterform: drop the column rather than let its colour vote. See _SPAN_INK_MAX_FRAC.
        if len(ink) > (y1 - y0) * _SPAN_INK_MAX_FRAC:
            continue
        if len(ink) >= 2:
            # The CORE of the stroke, not its average. Averaging every inked pixel folds in
            # the anti-aliased rim, which is a blend of ink and ground, and the result drifts
            # toward the background: capa19's near-black "shining" came out #4F4925 (a muddy
            # olive) and its white "the" came out #DCDAC7. Both read as washed out and the
            # Score fell even though the split itself was right. Keeping the pixels FURTHEST
            # from the ground recovers the true ink.
            dk = d[d > _SPAN_INK_MIN]
            core = ink[dk >= np.percentile(dk, 70)]
            cols.append((core if len(core) else ink).mean(axis=0))
    if len(cols) < 12:
        return None

    lo   = max(1, int(len(cols) * _SPAN_SIDE_MIN))
    best = (0.0, None)
    for i in range(lo, len(cols) - lo):
        c1 = np.mean(cols[:i], axis=0)
        c2 = np.mean(cols[i:], axis=0)
        d  = float(np.linalg.norm(c1 - c2))
        if d > best[0]:
            best = (d, (i / len(cols), c1, c2))
    if best[0] < _SPAN_GAP_MIN:
        return None
    frac, c1, c2 = best[1]
    return frac, _rgb_hex(c1), _rgb_hex(c2)


def _rgb_hex(c) -> str:
    r, g, b = (max(0, min(255, int(round(v)))) for v in c[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    _usage = (
        f"Uso: python {Path(__file__).name} <imagem> [width_cm] [height_cm]\n\n"
        "Extrai texto da imagem e imprime os elementos em JSON.\n\n"
        "Exemplos:\n"
        "  python ocr_extractor.py capa_teste4.png\n"
        "  python ocr_extractor.py capa.png 21.0 29.7\n\n"
        "Dependencias:\n"
        "  pip install easyocr Pillow numpy scikit-learn"
    )

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(_usage)
        sys.exit(0)

    _path    = sys.argv[1]
    _wcm     = float(sys.argv[2]) if len(sys.argv) > 2 else 21.0
    _hcm     = float(sys.argv[3]) if len(sys.argv) > 3 else 29.7

    print(f"[OCR] Processando: {_path}  ({_wcm} × {_hcm} cm)")
    _result = extract_text(_path, _wcm, _hcm)

    if not _result:
        print("\nNenhum texto detectado (ou EasyOCR nao instalado).")
        print("Instale com:  pip install easyocr")
        sys.exit(0)

    print(f"\n{len(_result)} elemento(s) detectado(s):\n")
    print(json.dumps(_result, ensure_ascii=False, indent=2))

    print("\n--- Resumo ---")
    for el in _result:
        bx = el["bbox_cm"]
        print(
            f"  {el['text']!r:30s}  "
            f"pos=({bx['x']:.2f}, {bx['y']:.2f})cm  "
            f"h={bx['h']:.2f}cm  "
            f"~{el['font_size_pt']}pt  "
            f"conf={el['confidence']:.2f}  "
            f"cor={el['color_hex']}"
        )
