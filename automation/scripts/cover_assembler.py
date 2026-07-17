#!/usr/bin/env python3
"""
cover_assembler.py — Assemble the cover_analysis.json from all CV/OCR modules.

This is the "source of truth" builder for the replication pipeline. It runs
all analysis modules in sequence and merges their outputs into a single JSON
document that tikz_generator (and optionally a VLM semantic pass) consumes.

Pipeline:
  image → [image_analyzer] → colors, regions, layout, text_zones, has_logo
        → [pattern_detector] → regions enriched with pattern metadata
        → [ocr_extractor]   → text_elements with bbox_cm
        → [font_matcher]    → text_elements enriched with font estimates
        → cover_analysis.json

Public API:
    assemble(image_path, output_path=None, width_cm=21.0, height_cm=29.7) -> dict

The returned dict (and the saved JSON) follows the schema documented at the
bottom of this file under _SCHEMA_COMMENT.
"""

import importlib.util as _ilu
import json
import time
from pathlib import Path

_HERE       = Path(__file__).resolve().parent
_OUTPUT_DIR = _HERE.parent / "output"


# ─── Module loader (avoids sys.path pollution) ────────────────────────────────

def _load_local(name: str):
    spec = _ilu.spec_from_file_location(name, _HERE / f"{name}.py")
    mod  = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── Public API ───────────────────────────────────────────────────────────────

def assemble(
    image_path:  "str | Path",
    output_path: "str | Path | None" = None,
    width_cm:    float = 21.0,
    height_cm:   float = 29.7,
) -> dict:
    """
    Run full CV+OCR analysis and produce cover_analysis.json.

    Parameters
    ----------
    image_path  : path to the cover image (PNG / JPEG / WEBP)
    output_path : where to write the JSON. Default: automation/output/cover_analysis.json
    width_cm    : physical canvas width in cm
    height_cm   : physical canvas height in cm

    Returns
    -------
    dict — the complete cover analysis schema
    """
    image_path  = Path(image_path).resolve()
    output_path = Path(output_path).resolve() if output_path else (
        _OUTPUT_DIR / "cover_analysis.json"
    )

    if not image_path.exists():
        raise FileNotFoundError(f"Imagem nao encontrada: {image_path}")

    t0 = time.monotonic()
    print(f"[ASSEMBLER] {image_path.name}  ({width_cm} × {height_cm} cm)")

    # ── Stage 1: CV analysis ─────────────────────────────────────────────────
    print("  [1/4] Analise CV (cores, regioes, layout)…")
    cv_data = _run_cv(image_path, width_cm, height_cm)
    _report_cv(cv_data)

    # ── Stage 2: Pattern detection on CV regions ──────────────────────────────
    print("  [2/4] Deteccao de padroes…")
    regions = cv_data.get("regions", []) if cv_data else []
    if regions:
        pat_mod = _load_local("pattern_detector")
        regions = pat_mod.detect_patterns(regions, width_cm, height_cm)
        n_pat   = sum(1 for r in regions if "pattern" in r)
        print(f"         {n_pat}/{len(regions)} regioes com padrao detectado")
    else:
        print("         (sem regioes para analisar)")

    # ── Stage 3: OCR ─────────────────────────────────────────────────────────
    print("  [3/4] OCR (texto + posicao)…")
    text_elements = _run_ocr(image_path, width_cm, height_cm)
    print(f"         {len(text_elements)} elemento(s) de texto detectado(s)")

    # ── Stage 4: Font matching ────────────────────────────────────────────────
    print("  [4/4] Estimativa de fontes…")
    if text_elements:
        font_mod      = _load_local("font_matcher")
        text_elements = font_mod.match_font(text_elements)
        pkgs          = {el["latex_pkg"] for el in text_elements if "latex_pkg" in el}
        print(f"         Pacotes detectados: {', '.join(sorted(pkgs)) or 'nenhum'}")
    else:
        print("         (sem texto para classificar)")

    # ── Assemble schema ───────────────────────────────────────────────────────
    doc = _build_schema(
        image_path    = image_path,
        cv_data       = cv_data,
        regions       = regions,
        text_elements = text_elements,
        width_cm      = width_cm,
        height_cm     = height_cm,
    )

    # ── Write JSON ────────────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    elapsed = time.monotonic() - t0
    print(f"  [OK] cover_analysis.json → {output_path}  ({elapsed:.1f}s)")

    return doc


# ─── Internal runners ─────────────────────────────────────────────────────────

def _run_cv(image_path: Path, width_cm: float, height_cm: float) -> "dict | None":
    try:
        mod = _load_local("image_analyzer")
        # Pass canvas dimensions so region bbox_cm coords match the TikZ canvas
        return mod.analyze_image(image_path, canvas_w_cm=width_cm, canvas_h_cm=height_cm)
    except Exception as exc:
        _s = str(exc)
        if "No module named" in _s:
            print("         CV indisponivel (numpy/sklearn/skimage ausentes)")
            return None
        print(f"         [!] CV falhou: {type(exc).__name__}: {_s[:80]}")
        return None


def _run_ocr(image_path: Path, width_cm: float, height_cm: float) -> list:
    try:
        mod = _load_local("ocr_extractor")
        return mod.extract_text(image_path, width_cm, height_cm)
    except Exception as exc:
        print(f"         [!] OCR falhou: {type(exc).__name__}: {str(exc)[:80]}")
        return []


def _report_cv(cv_data: "dict | None") -> None:
    if not cv_data or not cv_data.get("cv_available"):
        print("         CV indisponivel")
        return
    n_c  = len(cv_data.get("colors",  []))
    n_r  = len(cv_data.get("regions", []))
    lt   = cv_data.get("layout", {}).get("layout_type", "unknown")
    logo = "sim" if cv_data.get("has_logo") else "nao"
    print(f"         {n_c} cores | {n_r} regioes | layout={lt} | logo={logo}")


# ─── Schema builder ───────────────────────────────────────────────────────────

def _build_schema(
    image_path:    Path,
    cv_data:       "dict | None",
    regions:       list,
    text_elements: list,
    width_cm:      float,
    height_cm:     float,
) -> dict:
    colors     = (cv_data or {}).get("colors",     [])
    layout     = (cv_data or {}).get("layout",     {})
    text_zones = (cv_data or {}).get("text_zones", [])
    has_logo   = (cv_data or {}).get("has_logo",   False)
    cv_ok      = bool(cv_data and cv_data.get("cv_available"))

    # Patterns summary
    pat_types = {}
    for r in regions:
        p = r.get("pattern")
        if p:
            pat_types[p] = pat_types.get(p, 0) + 1

    # Dominant font package across all text elements
    pkg_votes: dict[str, int] = {}
    for el in text_elements:
        pkg = el.get("latex_pkg")
        if pkg:
            pkg_votes[pkg] = pkg_votes.get(pkg, 0) + 1
    dominant_pkg = max(pkg_votes, key=pkg_votes.get) if pkg_votes else "helvet"

    return {
        # ── Meta ─────────────────────────────────────────────────────────────
        "schema_version": "1.0",
        "source_image":   str(image_path),
        "canvas": {
            "width_cm":  width_cm,
            "height_cm": height_cm,
            "format":    _guess_format(width_cm, height_cm),
        },
        "cv_available":  cv_ok,
        "ocr_available": len(text_elements) > 0,

        # ── Color palette ─────────────────────────────────────────────────────
        # Sorted descending by coverage. Each: {hex, rgb, coverage}
        "colors": colors,

        # ── Geometric regions ─────────────────────────────────────────────────
        # Each region: {color_hex, shape, bbox_cm, area_frac}
        # May include: {pattern, foreach_axis, foreach_step_cm, foreach_count, foreach_anchor}
        "regions": regions,

        # ── Layout ───────────────────────────────────────────────────────────
        "layout": layout,

        # ── Text zones (from pixel variance, before OCR) ─────────────────────
        "text_zones": text_zones,

        # ── Logo heuristic ───────────────────────────────────────────────────
        "has_logo": has_logo,

        # ── Text elements (OCR + font match) ─────────────────────────────────
        # Each: {text, bbox_cm, font_size_pt, confidence, color_hex,
        #        latex_pkg, latex_cmd, font_family, weight_hint}
        "text_elements": text_elements,

        # ── Pattern summary ───────────────────────────────────────────────────
        "patterns_summary": {
            "total_tagged":  sum(pat_types.values()),
            "by_type":       pat_types,
            "has_foreach":   bool(pat_types),
        },

        # ── Typography summary ────────────────────────────────────────────────
        "typography": {
            "dominant_latex_pkg": dominant_pkg,
            "packages_detected":  list(pkg_votes.keys()),
        },
    }


def _guess_format(w: float, h: float) -> str:
    ratio = h / w if w > 0 else 0
    if abs(ratio - 297 / 210) < 0.12:
        return "A4"
    if abs(ratio - 279 / 216) < 0.12:
        return "US Letter"
    if abs(ratio - 1.0) < 0.08:
        return "Square"
    return "Custom"


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    _usage = (
        f"Uso: python {Path(__file__).name} <imagem> [output.json] [width_cm] [height_cm]\n\n"
        "Gera cover_analysis.json combinando CV + OCR + padroes + fonte.\n\n"
        "Exemplos:\n"
        "  python cover_assembler.py capas_teste/capa_teste4.png\n"
        "  python cover_assembler.py capa.png analise.json 21.0 29.7"
    )

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(_usage)
        sys.exit(0)

    _img  = sys.argv[1]
    _out  = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].endswith(".json") else None
    _wcm  = float(sys.argv[3]) if len(sys.argv) > 3 else 21.0
    _hcm  = float(sys.argv[4]) if len(sys.argv) > 4 else 29.7

    try:
        _doc = assemble(_img, _out, _wcm, _hcm)
        print(f"\n[DONE] {len(_doc['regions'])} regioes | "
              f"{len(_doc['text_elements'])} textos | "
              f"padroes={_doc['patterns_summary']['has_foreach']}")
    except FileNotFoundError as exc:
        print(f"\n[ERRO] {exc}", file=sys.stderr)
        sys.exit(1)


# ─── Schema reference ─────────────────────────────────────────────────────────
_SCHEMA_COMMENT = """
cover_analysis.json — complete schema

{
  "schema_version": "1.0",
  "source_image":   "/abs/path/to/image.png",
  "canvas":         {"width_cm": 21.0, "height_cm": 29.7, "format": "A4"},
  "cv_available":   true,
  "ocr_available":  true,

  "colors": [
    {"hex": "#1A1A1A", "rgb": [26,26,26], "coverage": 0.52},
    ...
  ],

  "regions": [
    {
      "color_hex":    "#1A1A1A",
      "shape":        "rectangle",
      "bbox_cm":      {"x": 0.0, "y": 0.0, "w": 21.0, "h": 20.0},
      "area_frac":    0.52,
      // Optional pattern fields:
      "pattern":          "grid",
      "foreach_axis":     "x",
      "foreach_step_cm":  7.0,
      "foreach_count":    3,
      "foreach_anchor":   {"x": 0.0, "y": 0.0, "w": 6.5, "h": 6.5}
    },
    ...
  ],

  "layout": {
    "layout_type": "top_graphic_bottom_text",
    "bands": [...]
  },

  "text_zones": [
    {"bbox_cm": {"x":0.5,"y":1.0,"w":20.0,"h":5.0}, "variance": 812.3},
    ...
  ],

  "has_logo": false,

  "text_elements": [
    {
      "text":         "david bowie",
      "bbox_cm":      {"x": 0.5, "y": 5.7, "w": 13.7, "h": 2.6},
      "font_size_pt": 73.5,
      "confidence":   0.998,
      "color_hex":    "#D9DFD5",
      "latex_pkg":    "helvet",
      "latex_cmd":    "\\sffamily",
      "font_family":  "Grotesque Sans",
      "weight_hint":  "bold",
      // Optional — added by VLM semantic pass:
      "semantic_role": "title"
    },
    ...
  ],

  "patterns_summary": {
    "total_tagged": 12,
    "by_type":      {"grid": 12},
    "has_foreach":  true
  },

  "typography": {
    "dominant_latex_pkg": "helvet",
    "packages_detected":  ["helvet"]
  }
}
"""
