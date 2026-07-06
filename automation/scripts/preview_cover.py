#!/usr/bin/env python3
"""
preview_cover.py — Render the first page of a PDF to PNG and open it.

Dependencies (pip-installable):
    pip install pymupdf

CLI usage:
    python preview_cover.py <output.pdf> [preview.png] [--dpi 150] [--page 0] [--no-open]
"""

import os
import sys
from pathlib import Path

_HERE        = Path(__file__).resolve().parent
_AUTOMATION  = _HERE.parent
_DEFAULT_OUT = _AUTOMATION / "output" / "cover_preview.png"


def render_pdf_page(
    pdf_path:   "str | Path",
    output_png: "str | Path | None" = None,
    dpi:        int = 150,
    page:       int = 0,
) -> Path:
    """
    Render one page of a PDF as a PNG file.

    Parameters
    ----------
    pdf_path   : path to the source PDF
    output_png : destination PNG (default: automation/output/cover_preview.png)
    dpi        : render resolution — 150 is good for checking, 300 for print QA
    page       : zero-based page index (0 = cover / first page)

    Returns
    -------
    Path  — absolute path of the written PNG

    Raises
    ------
    ImportError       if pymupdf is not installed
    FileNotFoundError if the PDF does not exist
    ValueError        if the requested page index is out of range
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise ImportError(
            "Pacote pymupdf nao instalado.\n"
            "Execute:  pip install pymupdf"
        ) from exc

    pdf_path   = Path(pdf_path).resolve()
    output_png = Path(output_png).resolve() if output_png else _DEFAULT_OUT

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF nao encontrado: {pdf_path}")

    output_png.parent.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    if page >= len(doc):
        doc.close()
        raise ValueError(
            f"Pagina {page} nao existe — o PDF tem {len(doc)} pagina(s)."
        )

    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = doc[page].get_pixmap(matrix=mat, alpha=False)
    pix.save(str(output_png))
    doc.close()

    return output_png


def open_preview(png_path: "str | Path") -> None:
    """Open the PNG in the default system image viewer (cross-platform)."""
    png_path = Path(png_path)
    if sys.platform == "win32":
        os.startfile(str(png_path))
    elif sys.platform == "darwin":
        import subprocess
        subprocess.run(["open", str(png_path)], check=False)
    else:
        import subprocess
        subprocess.run(["xdg-open", str(png_path)], check=False)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    usage = (
        f"Usage: python {Path(__file__).name} "
        "<output.pdf> [preview.png] [--dpi N] [--page N] [--no-open]\n\n"
        "  --dpi N     Resolucao de renderizacao (default: 150)\n"
        "  --page N    Numero da pagina, base 0 (default: 0 = capa)\n"
        "  --no-open   Gera o PNG mas nao abre o visualizador\n"
    )

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(usage)
        sys.exit(0)

    _pdf     = sys.argv[1]
    _out     = None
    _dpi     = 150
    _page    = 0
    _no_open = False

    _argv = sys.argv[2:]
    i = 0
    while i < len(_argv):
        a = _argv[i]
        if a == "--dpi" and i + 1 < len(_argv):
            _dpi = int(_argv[i + 1]); i += 2
        elif a == "--page" and i + 1 < len(_argv):
            _page = int(_argv[i + 1]); i += 2
        elif a == "--no-open":
            _no_open = True; i += 1
        elif not a.startswith("--"):
            _out = a; i += 1
        else:
            i += 1

    try:
        path = render_pdf_page(_pdf, _out, _dpi, _page)
        print(f"[OK] Preview salvo: {path}")
        if not _no_open:
            open_preview(path)
    except Exception as exc:
        print(f"[ERRO] {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
