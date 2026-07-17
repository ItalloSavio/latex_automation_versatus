#!/usr/bin/env python3
"""
font_matcher.py — Heuristic font family estimation from OCR bbox geometry.

Swiss Design covers almost exclusively use one of three typeface categories:
  - Grotesque sans-serif (Helvetica, Akzidenz-Grotesk, Univers)
  - Geometric sans-serif (Futura, Gill Sans)
  - Serif (rare in Swiss, but present in some vintage posters)

This module estimates which category a text element falls into using only
the information already available from the OCR output (no external calls):
  1. Character aspect ratio  (w / h per character)
  2. Stroke width estimate   (bbox height × empirical factor)
  3. Uppercase fraction      (ratio of uppercase letters in text)

Then maps the category to a LaTeX font package + command.

Public API:
    match_font(ocr_elements) -> list[dict]
    match_font_single(text, bbox_cm) -> dict

Each returned dict:
    latex_pkg      str  — LaTeX package name (e.g. "helvet", "avant", "lmodern")
    latex_cmd      str  — LaTeX font switch  (e.g. "\\sffamily", "\\rmfamily")
    font_family    str  — human-readable name (e.g. "Grotesque Sans")
    weight_hint    str  — "bold" | "regular" | "light"
    confidence     float — heuristic confidence [0, 1]
"""

from pathlib import Path


# ─── Font category → LaTeX mapping ───────────────────────────────────────────
#
# Each entry: (latex_pkg, latex_cmd, font_family)
# latex_pkg is used in \usepackage{}; latex_cmd switches to that font inline.

_FONT_MAP: "dict[str, tuple[str, str, str]]" = {
    "grotesque":  ("helvet",  r"\sffamily",  "Grotesque Sans"),
    "geometric":  ("avant",   r"\sffamily",  "Geometric Sans"),
    "serif":      ("lmodern", r"\rmfamily",  "Serif"),
    "monospace":  ("courier", r"\ttfamily",  "Monospace"),
    "fallback":   ("helvet",  r"\sffamily",  "Sans (fallback)"),
}

# Typical character aspect ratios (w/h per character) for each category.
# Grotesque: wide, nearly square characters  → ratio ≈ 0.55–0.75
# Geometric: slightly narrower              → ratio ≈ 0.45–0.62
# Serif:     variable, often narrower       → ratio ≈ 0.35–0.55
# Monospace: fixed-width, wider             → ratio ≈ 0.55–0.70
_ASPECT_RANGES: "dict[str, tuple[float, float]]" = {
    "grotesque":  (0.52, 0.80),
    "geometric":  (0.40, 0.62),
    "serif":      (0.30, 0.56),
    "monospace":  (0.52, 0.72),
}

# Swiss Design covers are ≥ 95% grotesque/geometric sans.
# We bias toward grotesque by default and only deviate when the aspect ratio
# strongly suggests serif or the text content contains lowercase descenders.
_SWISS_GROTESQUE_PRIOR = 0.70   # prior probability of grotesque in this domain

# Uppercase fraction threshold above which we lean toward display grotesque
_UPPER_THRESH = 0.65


# ─── Public API ───────────────────────────────────────────────────────────────

def match_font(ocr_elements: "list[dict]") -> "list[dict]":
    """
    Estimate font properties for each OCR element.

    Parameters
    ----------
    ocr_elements : list of dicts from ocr_extractor.extract_text()
                   Each must have at least: text (str), bbox_cm {w, h}

    Returns
    -------
    Same list with each dict enriched by: latex_pkg, latex_cmd,
    font_family, weight_hint, confidence.
    """
    return [_enrich(el.copy()) for el in ocr_elements]


def match_font_single(text: str, bbox_cm: dict) -> dict:
    """
    Estimate font properties for a single text element.

    Parameters
    ----------
    text    : recognized text string
    bbox_cm : dict with keys w (width cm) and h (height cm)

    Returns
    -------
    dict with: latex_pkg, latex_cmd, font_family, weight_hint, confidence
    """
    return _classify(text, bbox_cm)


# ─── Classification logic ─────────────────────────────────────────────────────

def _enrich(el: dict) -> dict:
    result = _classify(
        el.get("text", ""),
        el.get("bbox_cm", {}),
        el.get("stroke_ratio"),
    )
    el.update(result)
    return el


def _classify(text: str, bbox_cm: dict, stroke_ratio: "float | None" = None) -> dict:
    w = bbox_cm.get("w", 0.0)
    h = bbox_cm.get("h", 0.0)
    n_chars = max(len(text.replace(" ", "")), 1)

    # Character aspect ratio: width-per-character / height
    char_w  = w / n_chars if n_chars > 0 else 0.0
    ratio   = (char_w / h) if h > 1e-9 else 0.60   # 0.60 = grotesque default

    upper_frac = _uppercase_fraction(text)

    # Likely monospace: ratio very stable across chars AND typical coding chars
    if _looks_monospace(text, ratio):
        category = "monospace"
        conf     = 0.72
    elif _looks_serif(ratio, upper_frac):
        category = "serif"
        conf     = 0.58
    elif ratio < 0.50:
        category = "geometric"
        conf     = 0.62
    else:
        # Default: grotesque (Swiss Design prior)
        category = "grotesque"
        # Confidence rises when ratio is squarely in the grotesque band
        lo, hi = _ASPECT_RANGES["grotesque"]
        in_band = lo <= ratio <= hi
        conf    = 0.82 if in_band else 0.65

    # Apply Swiss Design domain prior — nudge uncertain serif toward grotesque
    if category == "serif" and conf < 0.65:
        category = "grotesque"
        conf     = _SWISS_GROTESQUE_PRIOR

    weight = _estimate_weight(text, h, stroke_ratio)
    pkg, cmd, family = _FONT_MAP[category]

    return {
        "latex_pkg":   pkg,
        "latex_cmd":   cmd,
        "font_family": family,
        "weight_hint": weight,
        "confidence":  round(conf, 2),
    }


def _uppercase_fraction(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def _looks_monospace(text: str, ratio: float) -> bool:
    mono_chars = set("0123456789abcdefABCDEF:./-_")
    code_frac  = sum(1 for c in text if c in mono_chars) / max(len(text), 1)
    return code_frac > 0.70 and 0.50 <= ratio <= 0.72


def _looks_serif(ratio: float, upper_frac: float) -> bool:
    lo, hi = _ASPECT_RANGES["serif"]
    in_band = lo <= ratio <= hi
    # Swiss covers rarely use serif; require strong aspect signal AND low uppercase
    return in_band and upper_frac < 0.40 and ratio < 0.48


# stroke-width ÷ em above which type reads as bold (matches ocr_extractor).
_BOLD_STROKE_RATIO = 0.125


def _estimate_weight(
    text:         str,
    height_cm:    float,
    stroke_ratio: "float | None" = None,
) -> str:
    """
    Estimate font weight.

    When a measured stroke-width ratio is available (from ocr_extractor's pixel
    analysis) it is the authority: thick strokes = bold. This correctly flags
    the heavy secondary type common on Swiss covers, which the size-only
    heuristic below misses. Falls back to geometry when no measurement exists.
    """
    if stroke_ratio is not None and stroke_ratio > 0:
        return "bold" if stroke_ratio >= _BOLD_STROKE_RATIO else "regular"

    if height_cm >= 1.0:
        return "bold"
    if len(text) <= 10 and text.isupper():
        return "bold"
    if height_cm < 0.35:
        return "light"
    return "regular"


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    _usage = (
        f"Uso: python {Path(__file__).name} <imagem> [width_cm] [height_cm]\n\n"
        "Estima a familia tipografica de cada texto detectado pelo OCR.\n\n"
        "Exemplo:\n"
        "  python font_matcher.py capas_teste/capa_teste4.png"
    )

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(_usage)
        sys.exit(0)

    # Load OCR via ocr_extractor (same directory)
    import importlib.util as _ilu

    def _load_mod(name: str) -> object:
        _spec = _ilu.spec_from_file_location(
            name, Path(__file__).parent / f"{name}.py"
        )
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod

    _path = sys.argv[1]
    _wcm  = float(sys.argv[2]) if len(sys.argv) > 2 else 21.0
    _hcm  = float(sys.argv[3]) if len(sys.argv) > 3 else 29.7

    print(f"[FONT] Processando: {_path}")
    _ocr_mod  = _load_mod("ocr_extractor")
    _elements = _ocr_mod.extract_text(_path, _wcm, _hcm)

    if not _elements:
        print("Nenhum texto detectado (verifique ocr_extractor e suas dependencias).")
        sys.exit(0)

    _enriched = match_font(_elements)

    print(f"\n{len(_enriched)} elemento(s) com estimativa de fonte:\n")
    print(json.dumps(_enriched, ensure_ascii=False, indent=2))

    print("\n--- Resumo ---")
    for el in _enriched:
        print(
            f"  {el['text']!r:30s}  "
            f"{el['font_family']:20s}  "
            f"{el['weight_hint']:8s}  "
            f"conf={el['confidence']:.2f}  "
            f"pkg={el['latex_pkg']}"
        )
