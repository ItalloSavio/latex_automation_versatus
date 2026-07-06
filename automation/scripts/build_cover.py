#!/usr/bin/env python3
"""
build_cover.py — Main pipeline orchestrator for the Intelligent Cover Compiler.

Full flow:
    Image  →  [Gemini Vision]  →  TikZ macro
           →  [LuaLaTeX]       →  PDF
           →  [preview_cover]  →  cover_preview.png  (opened automatically)
           →  [refine_tikz]    →  corrected TikZ  (optional, --refine)
           →  [LuaLaTeX]       →  refined PDF      (only when --refine)

CLI usage:
    python build_cover.py <cover_image.(png|jpg|jpeg|webp)> [options]

Options:
    --tex        <path>  Save generated TikZ macro here
                         Default: styles/versatus-dynamic-cover.tex
    --main       <file>  LaTeX entry-point filename
                         Default: main-dynamic.tex
    --brand      <name>  Apply brand palette from brands/<name>/brand.json
    --skip-vision        Skip Vision API call; reuse existing TikZ macro
    --refine             Run a second Gemini pass comparing reference vs result
    --refine-passes <n>  Number of refinement passes (default: 1, max: 3)
    --no-preview         Skip opening the preview PNG after compilation
    --dpi <n>            Preview PNG resolution (default: 150)

Required env var:  GEMINI_API_KEY
Optional env var:  GEMINI_MODEL  (default: gemini-2.5-flash)
"""

import argparse
import importlib.util
import io
import json
import sys
import time
from pathlib import Path

# Force UTF-8 stdout/stderr so box-drawing and emoji characters work on Windows
# (Windows PowerShell defaults to cp1252 which doesn't support these code points)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ─── Paths ────────────────────────────────────────────────────────────────────

_HERE         = Path(__file__).resolve().parent          # automation/scripts/
_AUTOMATION   = _HERE.parent                             # automation/
_PROJECT_ROOT = _AUTOMATION.parent                       # project root

_DEFAULT_TEX = _PROJECT_ROOT / "styles" / "versatus-dynamic-cover.tex"

# ─── Module loader ────────────────────────────────────────────────────────────

def _load_module(name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(name, file_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# ─── Pipeline steps ───────────────────────────────────────────────────────────

def _step_vision(image_path: Path, tex_path: Path, brand: "str | None" = None) -> None:
    """Phase 1 — Send image to Gemini Vision, extract TikZ macro directly."""
    extractor = _load_module("vision_extractor", _HERE / "vision_extractor.py")
    extractor.extract_tikz(image_path=image_path, output_tex=tex_path, brand=brand)


def _step_preview(pdf_path: Path, dpi: int = 150, open_it: bool = True) -> "Path | None":
    """
    Phase 3 — Render the PDF cover page to PNG and open it.
    Returns the PNG path, or None if pymupdf is not installed (warns and continues).
    """
    try:
        previewer = _load_module("preview_cover", _HERE / "preview_cover.py")
    except Exception as exc:
        print(f"    [!] Nao foi possivel carregar preview_cover: {exc}")
        return None

    try:
        png_path = previewer.render_pdf_page(pdf_path, dpi=dpi)
        print(f"    Preview PNG: {png_path}")
        if open_it:
            previewer.open_preview(png_path)
        return png_path
    except ImportError:
        print(
            "    [!] pymupdf nao instalado — preview ignorado.\n"
            "        Instale com:  pip install pymupdf"
        )
        return None
    except Exception as exc:
        print(f"    [!] Erro ao gerar preview: {exc}")
        return None


def _step_refine(
    image_path: Path,
    result_png: Path,
    tex_path:   Path,
    brand:      "str | None",
    pass_num:   int,
) -> None:
    """Phase 4 — Ask Gemini to compare reference vs result and output corrected TikZ."""
    extractor = _load_module("vision_extractor", _HERE / "vision_extractor.py")
    extractor.refine_tikz(
        reference_image = image_path,
        result_png      = result_png,
        output_tex      = tex_path,
        brand           = brand,
    )



# ─── CLI argument parsing ─────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog        = "build_cover.py",
        description = "Intelligent Cover Compiler: image → TikZ → PDF → preview [→ refine]",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Exemplos:\n"
            "  python build_cover.py cover.png --brand versatus\n"
            "  python build_cover.py cover.png --brand kosen --refine\n"
            "  python build_cover.py --skip-vision --brand versatus\n"
        ),
    )
    parser.add_argument(
        "image",
        nargs="?",
        help="Caminho da imagem de capa (PNG/JPEG/WEBP). Obrigatorio sem --skip-vision.",
    )
    parser.add_argument(
        "--tex",
        dest    = "tex_path",
        default = str(_DEFAULT_TEX),
        metavar = "PATH",
        help    = f"Arquivo .tex de saida (default: {_DEFAULT_TEX.relative_to(_PROJECT_ROOT)})",
    )
    parser.add_argument(
        "--main",
        dest    = "main_tex",
        default = "main-dynamic.tex",
        metavar = "FILE",
        help    = "Entry-point LaTeX (default: main-dynamic.tex)",
    )
    parser.add_argument(
        "--brand",
        dest    = "brand",
        default = None,
        metavar = "NOME",
        help    = "Marca (ex: versatus, kosen). Le brands/<NOME>/brand.json.",
    )
    parser.add_argument(
        "--skip-vision",
        dest   = "skip_vision",
        action = "store_true",
        help   = "Pula o Gemini Vision e reusa o .tex existente (sem reaplicar brand)",
    )
    parser.add_argument(
        "--reuse",
        action = "store_true",
        help   = "Reusa canvas_last.tikz e reaaplica brand/logo/preamble sem chamar a API",
    )
    parser.add_argument(
        "--refine",
        action = "store_true",
        help   = "Apos compilar, envia referencia + resultado ao Gemini para correcao",
    )
    parser.add_argument(
        "--refine-passes",
        dest    = "refine_passes",
        type    = int,
        default = 1,
        metavar = "N",
        help    = "Numero de passagens de refinamento (default: 1, max: 3)",
    )
    parser.add_argument(
        "--full-build",
        dest   = "full_build",
        action = "store_true",
        help   = "Apos o pipeline da capa, compila main.tex para gerar o livro completo",
    )
    parser.add_argument(
        "--no-preview",
        dest   = "no_preview",
        action = "store_true",
        help   = "Nao abre o visualizador apos gerar o preview PNG",
    )
    parser.add_argument(
        "--dpi",
        type    = int,
        default = 150,
        metavar = "N",
        help    = "Resolucao do preview PNG (default: 150)",
    )
    return parser.parse_args()

# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    args     = _parse_args()
    tex_path = Path(args.tex_path).resolve()

    _print_header()
    t_start = time.monotonic()

    # ── Phase 1: Vision → TikZ (ou cache/skip) ───────────────────────────────
    if args.reuse:
        print("[Phase 1] REUSE — reaplicando brand sobre canvas_last.tikz (sem API).")
        extractor = _load_module("vision_extractor", _HERE / "vision_extractor.py")
        try:
            extractor.reuse_tikz(output_tex=tex_path, brand=args.brand)
        except Exception as exc:
            print(f"\n[Phase 1 FALHOU] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 4
        image_path = None

    elif args.skip_vision:
        print("[Phase 1] Pulando Gemini Vision — reusando macro TikZ existente (sem reaplicar brand).")
        if not tex_path.exists():
            print(
                f"[ERRO] --skip-vision requer que o arquivo ja exista: {tex_path}",
                file=sys.stderr,
            )
            return 3
        print(f"          Macro : {tex_path}")
        image_path = None

    else:
        if not args.image:
            print(
                "[ERRO] Informe o caminho da imagem ou use --reuse / --skip-vision.",
                file=sys.stderr,
            )
            return 2

        image_path = Path(args.image).resolve()
        if not image_path.exists():
            print(f"[ERRO] Imagem nao encontrada: {image_path}", file=sys.stderr)
            return 3

        print("[Phase 1] Gemini Vision → TikZ")
        print(f"          Imagem : {image_path}")
        print(f"          Macro  : {tex_path}")
        if args.brand:
            print(f"          Brand  : {args.brand}")
        try:
            _step_vision(image_path, tex_path, brand=args.brand)
        except Exception as exc:
            print(f"\n[Phase 1 FALHOU] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 4

    compiler = _load_module("latex_compiler", _AUTOMATION / "core" / "latex_compiler.py")

    def _compile() -> "Path | int":
        """Run LuaLaTeX; return pdf_path on success, error code int on failure."""
        print(f"\n[Phase 2] Compilando com LuaLaTeX…")
        print(f"          Entry : {args.main_tex}")
        print(f"          Macro : {tex_path.relative_to(_PROJECT_ROOT)}")
        try:
            return compiler.compile_with_healing(
                project_root    = _PROJECT_ROOT,
                output_tex_path = tex_path,
                tex_file        = args.main_tex,
                tikz_ready      = True,
            )
        except compiler.CompilationError as exc:
            print(f"\n[Phase 2 FALHOU] Compilacao falhou.", file=sys.stderr)
            print(f"  Log  : {exc.log_path}", file=sys.stderr)
            print(
                f"  Erro : {exc.errors[0].splitlines()[0][:120] if exc.errors else '(nenhum)'}",
                file=sys.stderr,
            )
            return 5
        except Exception as exc:
            import traceback
            print(f"\n[Phase 2 FALHOU] {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return 6

    # ── Phase 2: Compilacao LuaLaTeX ─────────────────────────────────────────
    result = _compile()
    if isinstance(result, int):
        return result
    pdf_path = result

    # ── Phase 3: Preview PNG ──────────────────────────────────────────────────
    print(f"\n[Phase 3] Gerando preview PNG…")
    preview_png = _step_preview(pdf_path, dpi=args.dpi, open_it=not args.no_preview)

    # ── Phase 4: Refinamento (opcional) ──────────────────────────────────────
    if args.refine:
        if image_path is None:
            print(
                "\n[Phase 4] AVISO: --refine ignorado com --skip-vision "
                "(imagem de referencia nao disponivel).",
                file=sys.stderr,
            )
        elif preview_png is None:
            print(
                "\n[Phase 4] AVISO: --refine ignorado — preview PNG nao gerado "
                "(instale pymupdf para habilitar).",
                file=sys.stderr,
            )
        else:
            passes = max(1, min(args.refine_passes, 3))
            for i in range(1, passes + 1):
                print(f"\n[Phase 4] Refinamento — passagem {i}/{passes}…")
                try:
                    _step_refine(image_path, preview_png, tex_path, args.brand, i)
                except Exception as exc:
                    print(
                        f"\n[Phase 4 FALHOU] {type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
                    break

                # Recompilar com TikZ refinado
                result = _compile()
                if isinstance(result, int):
                    return result
                pdf_path = result

                # Atualizar preview
                print(f"\n[Phase 3b] Atualizando preview PNG…")
                preview_png = _step_preview(
                    pdf_path, dpi=args.dpi, open_it=not args.no_preview
                )

    # ── Phase 5: Full book (optional) ────────────────────────────────────────
    full_pdf_path = None
    if args.full_build:
        main_tex = "main.tex"
        print(f"\n[Phase 5] Compilando livro completo: {main_tex}")
        try:
            full_pdf_path = compiler.compile_with_healing(
                project_root    = _PROJECT_ROOT,
                output_tex_path = tex_path,
                tex_file        = main_tex,
                tikz_ready      = True,
            )
            print(f"          Livro  : {full_pdf_path}")
        except compiler.CompilationError as exc:
            print(f"\n[Phase 5 FALHOU] Compilacao do livro falhou.", file=sys.stderr)
            print(f"  Log  : {exc.log_path}", file=sys.stderr)
            print(
                f"  Erro : {exc.errors[0].splitlines()[0][:120] if exc.errors else '(nenhum)'}",
                file=sys.stderr,
            )
        except Exception as exc:
            import traceback
            print(f"\n[Phase 5 FALHOU] {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    # ── Done ──────────────────────────────────────────────────────────────────
    elapsed = time.monotonic() - t_start
    _print_success(pdf_path, tex_path, preview_png, elapsed, full_pdf_path)
    return 0


def _print_header() -> None:
    print("=" * 60)
    print("  Versatus Intelligent Cover Compiler  v0.2")
    print("=" * 60)
    print()


def _print_success(
    pdf_path:      Path,
    tex_path:      Path,
    preview_png:   "Path | None",
    elapsed:       float,
    full_pdf_path: "Path | None" = None,
) -> None:
    raw_tikz = _AUTOMATION / "output" / "canvas_last.tikz"
    print()
    print("=" * 60)
    print("  PIPELINE COMPLETO")
    print("-" * 60)
    print(f"  Capa PDF -> {str(pdf_path)[-50:]}")
    if full_pdf_path:
        print(f"  Livro    -> {str(full_pdf_path)[-50:]}")
    print(f"  TikZ     -> {str(tex_path)[-50:]}")
    if preview_png and preview_png.exists():
        print(f"  Preview  -> {str(preview_png)[-50:]}")
    if raw_tikz.exists():
        print(f"  Raw      -> {str(raw_tikz)[-50:]}")
    print(f"  Tempo    -> {elapsed:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
