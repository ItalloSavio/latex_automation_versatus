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
    --height-cm F      Canvas height in cm (default: derived from image aspect)
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

_RESIDUAL_ROUNDS  = 3       # how many residual→propose→gate cycles to run at most
_RESIDUAL_MIN_PCT = 0.15    # a blob under this share of the cover isn't worth a round
_RESIDUAL_GUARD   = 0.005   # Score may dip this much across rounds before the net trips


def _residual_of(analysis, image_path, render_path, top=6):
    """The system's own read of where it is still wrong (see visual_comparator)."""
    try:
        return _load("visual_comparator").residual_blobs(
            image_path, render_path, analysis.get("canvas", {}), top=top)
    except Exception as exc:
        _log(f"  [residuo] indisponivel ({exc})")
        return []


def _vlm_pass(analysis, image_path, render_path, cover_dir, score_fn, refresh):
    """Fase 5 — the VLM proposer, gated, driven by the system's OWN RESIDUAL and ITERATED.

    Each round: render the current best → measure where it still disagrees with the original
    → hand those exact boxes to the VLM → gate every proposed edit → repeat. It stops when
    no blob is left worth fixing, when a round lands nothing, or at _RESIDUAL_ROUNDS.

    This is the piece that takes the dev out of the loop: previously a human read the diff
    map, decided what each smudge was and wrote a detector. Rounds are CACHED so a re-run is
    deterministic and free (`--vlm-refresh` to re-call). Returns (best_analysis, quality)."""
    eg = _load("edit_gate")
    vp = _load("vlm_proposer")
    cache = cover_dir / "vlm_edits.json"
    cached_rounds = None
    if cache.exists() and not refresh:
        raw = json.loads(cache.read_text(encoding="utf-8"))
        # legacy caches hold a single flat list of edits; treat it as round 1
        cached_rounds = raw.get("rounds") if isinstance(raw, dict) else [raw]
        _log(f"  [VLM] cache com {len(cached_rounds)} rodada(s) ({cache.name}; "
             f"--vlm-refresh p/ rechamar)")

    best, quality = eg.assign_ids(analysis), None
    kept, kept_q = None, None                      # best across ROUNDS (never end worse)
    rounds_out, canvas = [], analysis.get("canvas", {})
    for rnd in range(_RESIDUAL_ROUNDS):
        quality = score_fn(best) or quality        # render the CURRENT best for the residual
        if kept is None or (quality or {}).get("score", -1) > (kept_q or {}).get("score", -1):
            kept, kept_q = copy.deepcopy(best), quality
        blobs = _residual_of(best, image_path, render_path)
        blobs = [b for b in blobs if b["area_pct"] >= _RESIDUAL_MIN_PCT]
        # The residual GUIDES the VLM; it must not GATE it. On a text-dominated cover the
        # blob finder is blind by construction (thin type survives no morphological opening),
        # so "no blobs" on the FIRST round would skip the pass that adds the text — capa2
        # lost its whole VLM contribution that way (0.3457 → 0.3352). From round 2 on, an
        # empty residual is the honest stop signal.
        if not blobs and rnd > 0:
            _log(f"  [residuo] rodada {rnd+1}: nenhuma mancha relevante — capa considerada pronta")
            break
        _log(f"  [residuo] rodada {rnd+1}: {len(blobs)} mancha(s)"
             + ("  (resíduo cego aqui — texto fino; seguindo mesmo assim)" if not blobs else ""))
        for b in blobs:
            _log(f"    {b['area_pct']:>5.2f}% em {b['bbox_cm']}  "
                 f"{b['orig_hex']} -> {b['render_hex']}")

        if cached_rounds is not None and rnd < len(cached_rounds):
            edits = cached_rounds[rnd]
        elif cached_rounds is not None:
            break                                   # cache exhausted, don't spend API
        else:
            _log("  [VLM] chamando Gemini (visao)...")
            edits = vp.propose(best, image_path, render_path,
                               zones=vp.zones_for(image_path, render_path), blobs=blobs)
            _log(f"  [VLM] Gemini propos {len(edits)} edits")
        if not edits:
            break

        edits = eg.snap_text_adds(edits, image_path, canvas)          # ink-snap positions
        edits = eg.snap_region_colors(edits, image_path, canvas,
                                      best.get("colors", []))         # measure the fill
        best, quality, log = eg.run_gate(best, edits, score_fn)
        best = eg.dedup_text(best)
        for e in log:
            _log(f"    {e['verdict']:16} {e['op']:14} {e['info']}")
        rounds_out.append(edits)
        if not any(e["verdict"].startswith("✓") for e in log):
            _log("  [residuo] rodada sem nenhum edit aceito — parando")
            break

    # Round-level safety net. It must NOT be a raw-Score hill-climb: the Score is blind to
    # thin type, so a round that correctly ADDS text always costs ~0.005 and a naive revert
    # throws that text away (measured: capa6 lost all three of its approved blocks). The
    # honest discriminator is text_match — adding text raises it, DUPLICATING text lowers it
    # (precision drops). So revert only when the Score fell materially AND text got no better.
    final_q = score_fn(best) or quality
    ds = (kept_q or {}).get("score", -1) - (final_q or {}).get("score", -1)
    t_keep, t_final = (kept_q or {}).get("text_match"), (final_q or {}).get("text_match")
    text_worse = (t_final is not None and t_keep is not None and t_final < t_keep - 1e-4)
    if kept is not None and ds > _RESIDUAL_GUARD and (text_worse or t_final is None):
        _log(f"  [residuo] rodadas pioraram "
             f"({(final_q or {}).get('score', 0):.4f} < {(kept_q or {}).get('score', 0):.4f}, "
             f"texto {t_keep}→{t_final}) — voltando ao melhor")
        best, quality = kept, kept_q
        score_fn(best)                              # re-render the kept state as deliverable
    else:
        quality = final_q

    if cached_rounds is None and rounds_out:
        cache.write_text(json.dumps({"rounds": rounds_out}, ensure_ascii=False, indent=2),
                         encoding="utf-8")
        _log(f"  [VLM] {len(rounds_out)} rodada(s) cacheadas em {cache.name}")
    n_gap = eg.persist_vocab_gaps(best, cover_dir.name)
    if n_gap:
        _log(f"  [VLM] {n_gap} vocab.gap -> output/vocab_gaps.jsonl (fila do dev)")
    return best, quality


def replicate(
    image_path:     "str | Path",
    out_dir:        "str | Path | None" = None,
    semantic:       bool  = False,
    max_passes:     int   = 5,
    ssim_threshold: float = 0.95,
    dpi:            int   = 150,
    width_cm:       float = 21.0,
    height_cm:      "float | None" = None,
    vlm:            bool  = False,
    vlm_refresh:    bool  = False,
) -> dict:
    """
    Full replication pipeline: image → PDF + quality report.

    The canvas ASPECT RATIO must match the input image, otherwise the final
    resize (render → original size, done by the comparator) stretches the whole
    layout and tanks SSIM. So height_cm is derived from the image's own aspect
    unless the caller passes an explicit value; width_cm is just the reference
    scale (SSIM works on pixels, the absolute cm size is irrelevant).

    Returns
    -------
    dict with keys: analysis_path, tikz_path, pdf_path, render_png_path,
                    quality (the visual_comparator report from the last pass),
                    passes (number of correction loops run)
    """
    image_path = Path(image_path).resolve()
    if not image_path.exists():
        raise FileNotFoundError(f"Imagem nao encontrada: {image_path}")

    if height_cm is None:
        from PIL import Image  # noqa: PLC0415
        with Image.open(image_path) as _im:
            w_px, h_px = _im.size
        height_cm = round(width_cm * h_px / w_px, 2)
        _log(f"  [canvas] {w_px}x{h_px}px → {width_cm} x {height_cm} cm "
             f"(aspect {w_px/h_px:.3f})")

    out_dir = Path(out_dir).resolve() if out_dir else (
        _AUTOMATION / "output" / "replicated"
    )
    # One subfolder per cover, with clean names — keeps `replicated/` tidy.
    stem          = image_path.stem
    cover_dir     = out_dir / stem
    cover_dir.mkdir(parents=True, exist_ok=True)

    analysis_path = cover_dir / "analysis.json"
    tikz_path     = cover_dir / "cover.tikz"
    tex_path      = cover_dir / "cover.tex"
    pdf_path      = cover_dir / "cover.pdf"
    render_path   = cover_dir / "render.png"
    diff_path     = cover_dir / "diff.png"

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

    generator  = _load("tikz_generator")
    comparator = _load("visual_comparator")
    calibrator = _load("calibrator")

    # One render+measure of a candidate analysis → its Score (or None on failure).
    # Used both to CHOOSE which detector layers to keep and to run the loop below.
    def _score_of(a: dict) -> "dict | None":
        generator.generate(a, tikz_path)
        _write_tex_wrapper(tex_path, tikz_path, a, width_cm, height_cm)
        ok, _err = _compile_lualatex(tex_path, pdf_path)
        if not ok or _render_pdf(pdf_path, render_path, dpi) is None:
            return None
        return comparator.compare(image_path, render_path, analysis=a,
                                  output_dir=cover_dir, ssim_threshold=ssim_threshold)

    # ── Stage 7: layer selection (measured "confidence") ──────────────────
    # Each detector (grid, circles) proposes a LAYER. Instead of trusting a
    # detector blindly (which caused regressions), we MEASURE: drop a layer and
    # keep it dropped only if the Score improves without it. This is how a cover
    # with no real grid (capa7) can shed the grid the detector wrongly imposed.
    _step(7, "Selecao de camadas (mede a contribuicao de cada detector)")
    analysis = _select_reader(analysis, image_path, _score_of)
    analysis = _select_layers(analysis, _score_of)

    # ── Stages 8–11: self-correcting loop ─────────────────────────────────
    # Hill climbing on the SCORE: a pass is only kept when the Score improved
    # (Score weights content over raw SSIM, so the loop can't "fix the background
    # and wreck the content"). A worse pass is reverted and the loop stops.
    quality       = None
    pass_count    = 0
    best_score    = -1.0
    best_analysis = None
    best_quality  = None

    for _pass in range(1, max_passes + 1):
        pass_count = _pass
        _step(8, f"Gerando TikZ  (pass {_pass}/{max_passes})")
        generator.generate(analysis, tikz_path)

        _step(9, "Compilando LuaLaTeX")
        _write_tex_wrapper(tex_path, tikz_path, analysis, width_cm, height_cm)
        ok, err = _compile_lualatex(tex_path, pdf_path)
        if not ok:
            _log(f"  [!] Compilacao falhou: {err[:200]}")
            break

        _step(10, "Renderizando PDF → PNG")
        rendered = _render_pdf(pdf_path, render_path, dpi)
        if rendered is None:
            _log("  [!] Render falhou — pymupdf nao instalado?")
            break
        render_path = rendered

        _step(11, "Comparando qualidade (Score / SSIM / content)")
        quality = comparator.compare(
            image_path, render_path,
            analysis=analysis,
            output_dir=cover_dir,
            ssim_threshold=ssim_threshold,
        )
        _rename_diff(cover_dir, diff_path)
        score = quality["score"]

        _log(f"  Score={score:.4f}  SSIM={quality['ssim_global']:.4f}  "
             f"content={quality.get('content_match', 0):.3f}  "
             f"IoU={quality.get('content_iou', 0):.3f}  "
             f"color_dist={quality['color_dist_mean']:.1f}  "
             f"regions={quality['region_match_rate']*100:.0f}%")

        # ── Hill climbing on the SCORE: keep the best, never regress ───────
        _EPS = 1e-4
        if score > best_score + _EPS:
            best_score    = score
            best_analysis = copy.deepcopy(analysis)
            best_quality  = quality
        elif score >= best_score - _EPS:
            _log(f"  [=] Convergiu (plateau em Score {best_score:.4f}) — parando")
            analysis, quality = best_analysis, best_quality
            break
        else:
            _log(f"  [!] Pass piorou (Score {best_score:.4f} → {score:.4f}) — revertendo")
            analysis, quality = best_analysis, best_quality
            _restore_best(generator, analysis, tex_path, tikz_path, pdf_path,
                          render_path, width_cm, height_cm, dpi)
            break

        if quality["score_pass"]:
            _log(f"  [PASS] Score >= {ssim_threshold}")
            break
        if _pass == max_passes:
            break

        # ── Propose the next candidate ────────────────────────────────────
        _step(12, "Calibrando pelo render + patches de cor")
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

    # ── Stage 13: VLM proposer on PLATEAU (Fase 5 — gated + cached) ───────────
    # The deterministic loop has settled. If still below the goal, run the VLM. The ADOPTED
    # analysis is cached (vlm_analysis.json) and, on reuse, rendered DIRECTLY — so the board
    # rebuild is fast, reproducible, and free of OCR/id drift (the bug that made the VLM work
    # vanish from the deliverable). The gate is the AUTHORITY (grounding + per-edit measured
    # guard + eye-wanted _TRUST_OPS): its output IS the deliverable, no blind-Score veto.
    if vlm and best_analysis is not None and not (best_quality or {}).get("score_pass"):
        _step(13, "VLM (Gemini) proponente de edits no PLATO")
        vlm_cache = cover_dir / "vlm_analysis.json"
        if vlm_cache.exists() and not vlm_refresh:
            best_analysis = json.loads(vlm_cache.read_text(encoding="utf-8"))
            _log(f"  [VLM] analysis ADOTADO do cache ({vlm_cache.name}; --vlm-refresh p/ refazer)")
        else:
            _score_of(best_analysis)   # current BEST render for the VLM to see
            best_analysis, _ = _vlm_pass(
                best_analysis, image_path, render_path, cover_dir, _score_of, vlm_refresh)
            vlm_cache.write_text(
                json.dumps(best_analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        # Render + persist the VLM result AS THE DELIVERABLE (the missing link before).
        best_quality = _score_of(best_analysis) or best_quality
        best_score   = (best_quality or {}).get("score", best_score)
        analysis, quality = best_analysis, best_quality
        _rename_diff(cover_dir, diff_path)
        analysis_path.write_text(
            json.dumps(best_analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        _log(f"  [VLM] deliverable atualizado -> Score {best_score:.4f}")

    _banner(f"DONE ({pass_count} pass(es))")
    if quality:
        _log(f"  Score final   : {quality.get('score', 0):.4f}  "
             f"({'PASS' if quality.get('score_pass') else 'FAIL'})")
        _log(f"  SSIM / content: {quality['ssim_global']:.4f} / "
             f"{quality.get('content_match', 0):.3f}")
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


def _select_reader(analysis: dict, image_path, score_fn) -> dict:
    """Choose between the detector stack and the generic structural reader — by MEASURING.

    Same discipline as _select_layers, and the same reason: a detector can be confidently
    wrong but a render cannot lie. The reader is offered BESIDE the detectors, never in
    place of them, so a cover the detectors already nail (capa4) keeps what works.

    The reader replaces only the SHAPES. Text stays exactly as the OCR read it, which is
    also why the reader masks the OCR boxes before tracing — otherwise letterforms come
    back as little polygons underneath the very words the text layer draws on top.
    """
    try:
        reader = _load("structural_reader")
        regions = reader.read(image_path, analysis)
    except Exception as exc:                       # a reader failure must never break a run
        _log(f"  leitor estrutural indisponivel ({type(exc).__name__}: {exc})")
        return analysis
    if not regions:
        _log("  leitor estrutural: recusou (imagem nao decompoe) → detectores")
        return analysis

    base = score_fn(analysis)
    cand = score_fn({**analysis, "regions": regions})
    s_det = base["score"] if base else -1.0
    s_rd  = cand["score"] if cand else -1.0
    if s_rd > s_det + 1e-3:
        _log(f"  leitor estrutural={s_rd:.4f} > detectores={s_det:.4f} → LEITOR "
             f"({len(regions)} pecas)")
        return {**analysis, "regions": regions}
    _log(f"  leitor estrutural={s_rd:.4f} <= detectores={s_det:.4f} → detectores")
    return analysis


def _select_layers(analysis: dict, score_fn) -> dict:
    """
    Keep a detector's layer only if it earns its place on the Score.

    Each optional layer (the circles, the whole grid) is dropped in turn; it is
    removed for good only when doing so IMPROVES the Score. Greedy and MEASURED —
    the reliable form of "confidence": a detector can be confidently wrong, but
    the render can't lie. Text and the background are always kept.

    This lets a cover with no real grid (capa7) shed the grid the detector wrongly
    imposed, without any per-cover heuristic — the measurement decides.
    """
    regions = analysis.get("regions", [])
    if not regions:
        return analysis

    optional = ("circle", "grid", "hatch")   # layers we are willing to drop
    grp = lambda r: (r.get("source") if r.get("source") in optional else "core")
    present = {grp(r) for r in regions} & set(optional)
    if not present:
        return analysis

    base = score_fn(analysis)
    if base is None:
        return analysis
    best_score, best_regions = base["score"], regions
    _log(f"  base Score={best_score:.4f}  (camadas: {', '.join(sorted(present))})")

    for layer in optional:
        if layer not in present:
            continue
        trial = [r for r in best_regions if grp(r) != layer]
        if len(trial) == len(best_regions):
            continue
        q  = score_fn({**analysis, "regions": trial})
        s2 = q["score"] if q else -1.0
        if s2 > best_score + 1e-3:            # only drop if it HELPS
            _log(f"  camada '{layer}': SEM={s2:.4f} > COM={best_score:.4f} → REMOVIDA")
            best_score, best_regions = s2, trial
        else:
            _log(f"  camada '{layer}': SEM={s2:.4f} ≤ COM={best_score:.4f} → mantida")

    return {**analysis, "regions": best_regions}


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
    parser.add_argument("--height-cm",      type=float, default=None,
                        help="Altura da canvas em cm (default: derivada do aspect da imagem)")
    parser.add_argument("--vlm",            action="store_true",
                        help="Passe do VLM (Gemini) no PLATO — proponente de edits, gated (requer GEMINI_API_KEY)")
    parser.add_argument("--vlm-refresh",    action="store_true",
                        help="Ignorar o cache de edits do VLM e rechamar o Gemini")

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
            vlm            = args.vlm,
            vlm_refresh    = args.vlm_refresh,
        )
        sys.exit(0 if (result["quality"] or {}).get("score_pass") else 1)

    except FileNotFoundError as exc:
        print(f"\n[ERRO] {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        import traceback
        print(f"\n[ERRO] {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(4)
