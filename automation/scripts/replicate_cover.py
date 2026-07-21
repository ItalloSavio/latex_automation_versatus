#!/usr/bin/env python3
"""
replicate_cover.py — Orchestrator for the Swiss Cover Replication pipeline.

Runs all 10 stages in sequence and optionally loops with the Patch Engine
when SSIM falls below the acceptable threshold.

Stages:
  1. CV analysis       image_analyzer  → colors, regions, layout
  2. Pattern detection pattern_detector → \foreach metadata
  3. OCR               ocr_extractor   → text elements
  4. Font matching     font_matcher    → LaTeX pkg per element
  5. Assembly          cover_assembler → cover_analysis.json
  6. [optional] VLM    Gemini + replicate_prompt.txt → enriched JSON
  7. TikZ generation   tikz_generator  → replicated_cover.tikz
  8. LaTeX compilation lualatex        → replicated_cover.pdf
  9. PDF render        pymupdf         → replicated_cover_render.png
 10. Quality compare   visual_comparator → SSIM / IoU / Color Distance

Patch Engine (runs when SSIM < threshold):
  - Applies color patches from visual_comparator.patch_hints to the JSON
  - Regenerates TikZ and recompiles
  - Loops up to --max-passes times

CLI usage:
    python replicate_cover.py <image.(png|jpg)> [options]

Options:
    --out-dir DIR      Output directory (default: automation/output/replicated/)
    --semantic         Enable VLM enrichment pass (requires GEMINI_API_KEY)
    --max-passes N     Maximum correction passes (default: 5)
    --ssim-threshold F Minimum acceptable SSIM (default: 0.95)
    --dpi N            PDF render DPI (default: 150)
    --width-cm F       Canvas width in cm (default: 21.0)
    --height-cm F      Canvas height in cm (default: 29.7)
"""

import copy
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_HERE       = Path(__file__).resolve().parent
_AUTOMATION = _HERE.parent
_ROOT       = _AUTOMATION.parent
_PROMPT_DIR = _AUTOMATION / "prompt"

_REPLICATE_PROMPT = _PROMPT_DIR / "replicate_prompt.txt"

# ─── Module loader ────────────────────────────────────────────────────────────

def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── Public API ───────────────────────────────────────────────────────────────

def replicate(
    image_path:     "str | Path",
    out_dir:        "str | Path | None" = None,
    semantic:       bool  = False,
    max_passes:     int   = 5,
    ssim_threshold: float = 0.95,
    dpi:            int   = 150,
    width_cm:       float = 21.0,
    height_cm:      float = 29.7,
) -> dict:
    """
    Full replication pipeline: image → PDF + quality report.

    Returns
    -------
    dict with keys: analysis_path, tikz_path, pdf_path, render_png_path,
                    quality (the visual_comparator report from the last pass),
                    passes (number of correction loops run)
    """
    image_path = Path(image_path).resolve()
    if not image_path.exists():
        raise FileNotFoundError(f"Imagem nao encontrada: {image_path}")

    out_dir = Path(out_dir).resolve() if out_dir else (
        _AUTOMATION / "output" / "replicated"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    stem          = image_path.stem
    analysis_path = out_dir / f"{stem}_analysis.json"
    tikz_path     = out_dir / f"{stem}_cover.tikz"
    tex_path      = out_dir / f"{stem}_cover.tex"
    pdf_path      = out_dir / f"{stem}_cover.pdf"
    render_path   = out_dir / f"{stem}_render.png"
    diff_path     = out_dir / f"{stem}_diff.png"

    _banner(f"REPLICATE: {image_path.name}")

    # ── Stages 1–5: Assembly ─────────────────────────────────────────────────
    _step(1, "Analise completa (CV + OCR + padroes + fonte)")
    assembler = _load("cover_assembler")
    analysis  = assembler.assemble(image_path, analysis_path, width_cm, height_cm)

    # ── Stage 6 (optional): VLM semantic enrichment ───────────────────────
    if semantic:
        _step(6, "VLM semantic enrichment (Gemini)")
        analysis = _run_semantic_pass(image_path, analysis, analysis_path)
    else:
        _log("  [modo] --local: sem chamada VLM")

    # ── Stages 7–11: self-correcting loop ─────────────────────────────────
    #
    # Each pass renders the current analysis, measures the result, and proposes
    # a correction. Two kinds of correction feed the next pass:
    #   - calibrator : measures the rendered ink of every text element and
    #                  solves its own scale/offset (no magic constants)
    #   - patch      : recolours regions the comparator found wrong
    # Hill climbing: a pass is only kept when SSIM improved. A pass that makes
    # things worse is reverted and the loop stops, so output never regresses.
    generator  = _load("tikz_generator")
    comparator = _load("visual_comparator")
    calibrator = _load("calibrator")

    quality       = None
    pass_count    = 0
    best_ssim     = -1.0
    best_analysis = None
    best_quality  = None

    for _pass in range(1, max_passes + 1):
        pass_count = _pass
        _step(7, f"Gerando TikZ  (pass {_pass}/{max_passes})")
        generator.generate(analysis, tikz_path)

        _step(8, "Compilando LuaLaTeX")
        _write_tex_wrapper(tex_path, tikz_path, analysis, width_cm, height_cm)
        ok, err = _compile_lualatex(tex_path, pdf_path)
        if not ok:
            _log(f"  [!] Compilacao falhou: {err[:200]}")
            break

        _step(9, "Renderizando PDF → PNG")
        rendered = _render_pdf(pdf_path, render_path, dpi)
        if rendered is None:
            _log("  [!] Render falhou — pymupdf nao instalado?")
            break
        render_path = rendered

        _step(10, "Comparando qualidade (SSIM / Color / Region)")
        quality = comparator.compare(
            image_path, render_path,
            analysis=analysis,
            output_dir=out_dir,
            ssim_threshold=ssim_threshold,
        )
        _rename_diff(out_dir, diff_path)
        ssim = quality["ssim_global"]

        _log(f"  SSIM={ssim:.4f}  "
             f"color_dist={quality['color_dist_mean']:.1f}  "
             f"regions={quality['region_match_rate']*100:.0f}%")

        # ── Hill climbing: keep the best, never regress ────────────────────
        _EPS = 1e-4
        if ssim > best_ssim + _EPS:
            best_ssim     = ssim
            best_analysis = copy.deepcopy(analysis)
            best_quality  = quality
        elif ssim >= best_ssim - _EPS:
            _log(f"  [=] Convergiu (plateau em {best_ssim:.4f}) — parando")
            analysis, quality = best_analysis, best_quality
            break
        else:
            _log(f"  [!] Pass piorou ({best_ssim:.4f} → {ssim:.4f}) — revertendo")
            analysis, quality = best_analysis, best_quality
            _restore_best(generator, analysis, tex_path, tikz_path, pdf_path,
                          render_path, width_cm, height_cm, dpi)
            break

        if quality["ssim_pass"]:
            _log(f"  [PASS] SSIM >= {ssim_threshold}")
            break
        if _pass == max_passes:
            break

        # ── Propose the next candidate ────────────────────────────────────
        _step(11, "Calibrando pelo render + patches de cor")
        analysis, n_cal = calibrator.calibrate(analysis, image_path, render_path)
        n_patch = len(quality["patch_hints"])
        if n_patch:
            analysis = _apply_patches(analysis, quality["patch_hints"])
        _log(f"  {n_cal} texto(s) calibrado(s), {n_patch} patch(es) de cor")

        if n_cal == 0 and n_patch == 0:
            _log("  [OK] Convergiu — nenhuma correcao restante")
            break

        analysis_path.write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    _banner(f"DONE ({pass_count} pass(es))")
    if quality:
        _log(f"  SSIM final    : {quality['ssim_global']:.4f}  "
             f"({'PASS' if quality['ssim_pass'] else 'FAIL'})")
        _log(f"  Regioes match : {quality['region_match_rate']*100:.0f}%")
        _log(f"  Diff map      : {diff_path}")
    _log(f"  PDF           : {pdf_path}")
    _log(f"  Render PNG    : {render_path}")

    return {
        "analysis_path":  str(analysis_path),
        "tikz_path":      str(tikz_path),
        "pdf_path":       str(pdf_path),
        "render_png_path": str(render_path),
        "quality":        quality,
        "passes":         pass_count,
    }


# ─── Stage 6: VLM semantic pass ──────────────────────────────────────────────

def _run_semantic_pass(
    image_path:    Path,
    analysis:      dict,
    analysis_path: Path,
) -> dict:
    """
    Send image + JSON to Gemini with replicate_prompt.txt.
    VLM adds semantic_role fields — never changes coordinates or colors.
    Returns enriched analysis dict (also updates analysis_path on disk).
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        _log("  [!] google-genai nao instalado — pulando passo semantico")
        return analysis

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        _log("  [!] GEMINI_API_KEY nao definida — pulando passo semantico")
        return analysis

    if not _REPLICATE_PROMPT.exists():
        _log(f"  [!] Prompt nao encontrado: {_REPLICATE_PROMPT}")
        return analysis

    system_prompt = _REPLICATE_PROMPT.read_text(encoding="utf-8")
    analysis_json = json.dumps(analysis, ensure_ascii=False, indent=2)
    user_text     = f"=== COVER ANALYSIS JSON ===\n{analysis_json}"

    mime      = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    img_bytes = image_path.read_bytes()

    client = genai.Client(http_options={"api_version": "v1beta"})
    models = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
    ]

    for model in models:
        try:
            _log(f"  [VLM] {model}…")
            parts = [
                types.Part(inline_data=types.Blob(data=img_bytes, mime_type=mime)),
                types.Part(text=user_text),
            ]
            resp = client.models.generate_content(
                model=model,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.05,
                    max_output_tokens=16384,
                ),
            )
            raw = resp.text.strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]

            enriched = json.loads(raw)
            enriched["semantic_pass"] = True
            analysis_path.write_text(
                json.dumps(enriched, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            _log(f"  [VLM] JSON enriquecido ({len(raw)} chars)")
            return enriched

        except Exception as exc:
            _log(f"  [!] {model}: {str(exc)[:80]}")
            continue

    _log("  [!] VLM falhou em todos os modelos — continuando sem enriquecimento")
    return analysis


# ─── Stage 8: LaTeX compilation ──────────────────────────────────────────────

def _write_tex_wrapper(
    tex_path:  Path,
    tikz_path: Path,
    analysis:  dict,
    width_cm:  float,
    height_cm: float,
) -> None:
    """Write a minimal standalone .tex that includes the TikZ cover block."""
    pkg  = analysis.get("typography", {}).get("dominant_latex_pkg", "helvet")
    w    = f"{width_cm}cm"
    h    = f"{height_cm}cm"
    rel  = tikz_path.name  # same directory as tex_path

    # For LuaLaTeX we use fontspec. Swiss covers are set in Helvetica, so we
    # prefer real Helvetica, then TeX Gyre Heros (a Helvetica-metric clone whose
    # letterforms match — much closer than Arial), and only fall back to Arial.
    font_setup = (
        r"\usepackage{fontspec}" + "\n"
        r"\IfFontExistsTF{Helvetica Neue}{\setmainfont{Helvetica Neue}\setsansfont{Helvetica Neue}}{%" + "\n"
        r"\IfFontExistsTF{Helvetica}{\setmainfont{Helvetica}\setsansfont{Helvetica}}{%" + "\n"
        r"\IfFontExistsTF{TeX Gyre Heros}{\setmainfont{TeX Gyre Heros}\setsansfont{TeX Gyre Heros}}{%" + "\n"
        r"\IfFontExistsTF{Arial}{\setmainfont{Arial}\setsansfont{Arial}}{%" + "\n"
        r"\setmainfont{Latin Modern Sans}\setsansfont{Latin Modern Sans}}}}}"
    )

    # NOTE: every line after \begin{document} ends with % to suppress whitespace.
    # A bare newline between \input and \RenderDynamicCover creates an empty
    # paragraph that pushes the TikZ picture to page 2, leaving page 1 blank.
    content = (
        r"\documentclass{article}" + "\n"
        r"\usepackage[margin=0pt," + f"paperwidth={w},paperheight={h}" + r"]{geometry}" + "\n"
        + font_setup + "\n"
        r"\usepackage{xcolor}" + "\n"
        r"\usepackage{graphicx}" + "\n"   # \scalebox for text nodes
        r"\usepackage{tikz}" + "\n"
        r"\usetikzlibrary{calc}" + "\n"
        r"\pagestyle{empty}" + "\n"
        r"\parindent=0pt" + "\n"
        r"\begin{document}%" + "\n"
        r"\input{" + rel + r"}%" + "\n"
        r"\RenderDynamicCover%" + "\n"
        r"\end{document}" + "\n"
    )
    tex_path.write_text(content, encoding="utf-8")


def _restore_best(
    generator,
    analysis:  dict,
    tex_path:  Path,
    tikz_path: Path,
    pdf_path:  Path,
    render_path: Path,
    width_cm:  float,
    height_cm: float,
    dpi:       int,
) -> None:
    """
    Re-emit the best-scoring analysis so the .tikz/.pdf/.png on disk match the
    metrics we report. Called when a pass regressed and we roll back to it.
    """
    generator.generate(analysis, tikz_path)
    _write_tex_wrapper(tex_path, tikz_path, analysis, width_cm, height_cm)
    ok, _ = _compile_lualatex(tex_path, pdf_path)
    if ok:
        _render_pdf(pdf_path, render_path, dpi)


def _compile_lualatex(
    tex_path: Path,
    pdf_path: Path,
) -> "tuple[bool, str]":
    """
    Run lualatex twice (for stable output) from the .tex file's directory.
    Returns (success, error_message).
    """
    cwd  = tex_path.parent
    name = tex_path.name

    for _run in range(2):
        result = subprocess.run(
            ["lualatex", "--interaction=nonstopmode", "--halt-on-error", name],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if result.returncode != 0:
            # Extract last relevant error from log
            log_lines = (result.stdout + result.stderr).splitlines()
            errors    = [l for l in log_lines if l.startswith("!") or "Error" in l]
            return False, "\n".join(errors[-5:]) if errors else result.stderr[-300:]

    # lualatex writes PDF next to the .tex file by default
    generated = tex_path.with_suffix(".pdf")
    if generated.exists() and generated != pdf_path:
        generated.rename(pdf_path)

    return pdf_path.exists(), "" if pdf_path.exists() else "PDF nao gerado"


# ─── Stage 9: PDF render ─────────────────────────────────────────────────────

def _render_pdf(pdf_path: Path, png_path: Path, dpi: int) -> "Path | None":
    """Render first page of PDF to PNG using pymupdf."""
    try:
        import fitz
        doc  = fitz.open(str(pdf_path))
        page = doc[0]
        mat  = fitz.Matrix(dpi / 72, dpi / 72)
        pix  = page.get_pixmap(matrix=mat, alpha=False)
        pix.save(str(png_path))
        doc.close()
        return png_path
    except ImportError:
        _log("  [!] pymupdf nao instalado: pip install pymupdf")
        return None
    except Exception as exc:
        _log(f"  [!] Render falhou: {exc}")
        return None


# ─── Patch Engine ─────────────────────────────────────────────────────────────

def _apply_patches(analysis: dict, patch_hints: list) -> dict:
    """
    Apply color correction patches to the analysis dict.
    Each patch: {element_id: "region_N", expected_hex: "#RRGGBB", ...}
    """
    import copy
    patched = copy.deepcopy(analysis)
    regions = patched.get("regions", [])

    for hint in patch_hints:
        eid = hint.get("element_id", "")
        if not eid.startswith("region_"):
            continue
        try:
            idx = int(eid.split("_", 1)[1])
        except (ValueError, IndexError):
            continue

        if 0 <= idx < len(regions):
            old = regions[idx].get("color_hex", "")
            regions[idx]["color_hex"] = hint["expected_hex"]
            _log(f"    Patch region_{idx}: {old} → {hint['expected_hex']}")

    # Also update the colors array to include any newly patched hexes
    existing_hexes = {c["hex"].upper() for c in patched.get("colors", [])}
    for hint in patch_hints:
        h = hint.get("expected_hex", "").upper()
        if h and h not in existing_hexes:
            patched.setdefault("colors", []).append({
                "hex": h, "rgb": _hex_to_rgb(h), "coverage": 0.0
            })
            existing_hexes.add(h)

    return patched


def _hex_to_rgb(h: str) -> list:
    h = h.lstrip("#")
    return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)]


def _rename_diff(out_dir: Path, target: Path) -> None:
    src = out_dir / "diff_map.png"
    if src.exists() and src != target:
        try:
            src.rename(target)
        except Exception:
            pass


# ─── Display helpers ──────────────────────────────────────────────────────────

def _banner(msg: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def _step(n: int, msg: str) -> None:
    print(f"\n[{n:02d}] {msg}")


def _log(msg: str) -> None:
    print(msg)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Replica uma capa Swiss Design como TikZ/PDF fiel.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("image", help="Imagem de entrada (PNG/JPEG)")
    parser.add_argument("--out-dir",        default=None,  help="Diretorio de saida")
    parser.add_argument("--semantic",       action="store_true",
                        help="Habilitar passo VLM (requer GEMINI_API_KEY)")
    parser.add_argument("--max-passes",     type=int,   default=5,
                        help="Numero maximo de passes de correcao (default: 3)")
    parser.add_argument("--ssim-threshold", type=float, default=0.95,
                        help="SSIM minimo aceitavel (default: 0.95)")
    parser.add_argument("--dpi",            type=int,   default=150,
                        help="DPI para render do PDF (default: 150)")
    parser.add_argument("--width-cm",       type=float, default=21.0,
                        help="Largura da canvas em cm (default: 21.0)")
    parser.add_argument("--height-cm",      type=float, default=29.7,
                        help="Altura da canvas em cm (default: 29.7)")

    args = parser.parse_args()

    try:
        result = replicate(
            image_path     = args.image,
            out_dir        = args.out_dir,
            semantic       = args.semantic,
            max_passes     = args.max_passes,
            ssim_threshold = args.ssim_threshold,
            dpi            = args.dpi,
            width_cm       = args.width_cm,
            height_cm      = args.height_cm,
        )
        sys.exit(0 if (result["quality"] or {}).get("ssim_pass") else 1)

    except FileNotFoundError as exc:
        print(f"\n[ERRO] {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        import traceback
        print(f"\n[ERRO] {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(4)
