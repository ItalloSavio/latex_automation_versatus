#!/usr/bin/env python3
"""
build_cover.py — Main pipeline orchestrator for the Intelligent Cover Compiler.

Full flow:
    Image  →  [Gemini Vision]  →  Canvas AST JSON
           →  [json_to_tikz]   →  versatus-dynamic-cover.tex
           →  [LuaLaTeX]       →  main.pdf
           →  [Self-Healing]   →  retry on error (max 3x)

CLI usage:
    python build_cover.py <cover_image.(png|jpg|jpeg|webp)> [options]

Options:
    --json   <path>   Save intermediate Canvas AST JSON here
                      Default: automation/output/canvas_last.json
    --tex    <path>   Save generated TikZ macro here
                      Default: styles/versatus-dynamic-cover.tex
    --main   <file>   LaTeX entry-point filename
                      Default: main-dynamic.tex
    --retries <n>     Max self-healing retries (default: 3)
    --skip-vision     Skip Vision API call; reuse existing --json file

Required env var:  GEMINI_API_KEY
Optional env var:  GEMINI_MODEL  (default: gemini-2.0-flash-lite)
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

def _step_vision(image_path: Path, tex_path: Path) -> None:
    """Phase 1 — Send image to Gemini Vision, extract TikZ macro directly."""
    extractor = _load_module("vision_extractor", _HERE / "vision_extractor.py")
    extractor.extract_tikz(image_path=image_path, output_tex=tex_path)



# ─── CLI argument parsing ─────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog        = "build_cover.py",
        description = "Intelligent Cover Compiler: image → Gemini Vision → TikZ → PDF",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Exemplos:\n"
            "  python build_cover.py cover.png\n"
            "  python build_cover.py cover.jpg\n"
            "  python build_cover.py --skip-vision          (reusa styles/versatus-dynamic-cover.tex)\n"
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
        "--skip-vision",
        dest   = "skip_vision",
        action = "store_true",
        help   = "Pula o Gemini Vision e reusa o styles/versatus-dynamic-cover.tex existente",
    )
    return parser.parse_args()

# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    args     = _parse_args()
    tex_path = Path(args.tex_path).resolve()

    _print_header()
    t_start = time.monotonic()

    # ── Phase 1: Vision → TikZ ───────────────────────────────────────────────
    if args.skip_vision:
        print("[Phase 1] Pulando Gemini Vision — reusando macro TikZ existente.")
        if not tex_path.exists():
            print(
                f"[ERRO] --skip-vision requer que o arquivo ja exista: {tex_path}",
                file=sys.stderr,
            )
            return 3
        print(f"          Macro : {tex_path}")
    else:
        if not args.image:
            print(
                "[ERRO] Informe o caminho da imagem ou use --skip-vision.",
                file=sys.stderr,
            )
            return 2

        image_path = Path(args.image).resolve()
        if not image_path.exists():
            print(f"[ERRO] Imagem nao encontrada: {image_path}", file=sys.stderr)
            return 3

        print(f"[Phase 1] Gemini Vision → TikZ")
        print(f"          Imagem : {image_path}")
        print(f"          Macro  : {tex_path}")
        try:
            _step_vision(image_path, tex_path)
        except Exception as exc:
            print(f"\n[Phase 1 FALHOU] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 4

    # ── Phase 2: Compilacao LuaLaTeX ─────────────────────────────────────────
    print(f"\n[Phase 2] Compilando com LuaLaTeX…")
    print(f"          Entry : {args.main_tex}")
    print(f"          Macro : {tex_path.relative_to(_PROJECT_ROOT)}")

    compiler = _load_module("latex_compiler", _AUTOMATION / "core" / "latex_compiler.py")

    try:
        pdf_path = compiler.compile_with_healing(
            project_root    = _PROJECT_ROOT,
            output_tex_path = tex_path,
            tex_file        = args.main_tex,
            tikz_ready      = True,
        )
    except compiler.CompilationError as exc:
        elapsed = time.monotonic() - t_start
        print(f"\n[Phase 2 FALHOU] Compilacao falhou.", file=sys.stderr)
        print(f"  Log  : {exc.log_path}", file=sys.stderr)
        print(
            f"  Erro : {exc.errors[0].splitlines()[0][:120] if exc.errors else '(nenhum)'}",
            file=sys.stderr,
        )
        print(f"  Tempo: {elapsed:.1f}s", file=sys.stderr)
        return 5
    except Exception as exc:
        import traceback
        print(f"\n[Phase 2 FALHOU] {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 6

    # ── Done ──────────────────────────────────────────────────────────────────
    elapsed = time.monotonic() - t_start
    _print_success(pdf_path, tex_path, elapsed)
    return 0


def _print_header() -> None:
    print("=" * 60)
    print("  Versatus Intelligent Cover Compiler  v0.2")
    print("=" * 60)
    print()


def _print_success(pdf_path: Path, tex_path: Path, elapsed: float) -> None:
    raw_tikz = _AUTOMATION / "output" / "canvas_last.tikz"
    print()
    print("=" * 60)
    print("  PIPELINE COMPLETO")
    print("-" * 60)
    print(f"  PDF      -> {str(pdf_path)[-48:]}")
    print(f"  TikZ     -> {str(tex_path)[-48:]}")
    if raw_tikz.exists():
        print(f"  Raw      -> {str(raw_tikz)[-48:]}")
    print(f"  Tempo    -> {elapsed:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
