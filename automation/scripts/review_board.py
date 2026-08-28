#!/usr/bin/env python3
"""
review_board.py — one glance at all covers: original vs render + SSIM/content.

Renders a single board image so the HUMAN eye can judge every cover at once —
the visual regression gate that pairs with the numeric metrics. It only reads the
renders already on disk (from replicate_cover.py); pass --build to (re)generate
every cover first.

Usage:
    python automation/scripts/review_board.py            # board from existing renders
    python automation/scripts/review_board.py --build    # rebuild all covers, then board
    python automation/scripts/review_board.py 4 6 7      # only these covers

Output: automation/output/replicated/_review_board.png
"""

import subprocess
import sys
from pathlib import Path

_HERE     = Path(__file__).resolve().parent
_ROOT     = _HERE.parent.parent
_COVERS   = _ROOT / "capas_teste"
_OUT      = _HERE.parent / "output" / "replicated"
_BOARD    = _OUT / "_review_board.png"
_THUMB_H  = 300   # px height of each cover thumbnail


def _discover(args: "list[str]") -> "list[int]":
    """Cover numbers to show: CLI digits, else every capa_teste*.png found."""
    nums = [int(a) for a in args if a.isdigit()]
    if nums:
        return sorted(nums)
    found = []
    for p in sorted(_COVERS.glob("capa_teste*.png")):
        digits = "".join(c for c in p.stem if c.isdigit())
        if digits:
            found.append(int(digits))
    return sorted(found)


def _build(nums: "list[int]") -> None:
    """Re-run the pipeline for each cover (1 pass) so the renders are current.
    Passes --vlm so the board shows the ADOPTED VLM render (the deliverable the eye
    judges), not the deterministic one — and reuses the cached vlm_edits.json, so a
    rebuild spends NO API. Without --vlm, --build overwrote render.png with the plain
    deterministic render and every VLM gain vanished from the board."""
    for n in nums:
        img = _COVERS / f"capa_teste{n}.png"
        if not img.exists():
            continue
        print(f"[build] capa_teste{n} …", flush=True)
        subprocess.run(
            [sys.executable, str(_HERE / "replicate_cover.py"), str(img),
             "--max-passes", "1", "--vlm"],
            capture_output=True, text=True,
        )


def _metrics(orig, rend, analysis=None) -> "tuple[float, float, float]":
    """Score + SSIM + the content term via the comparator's own funcs (single source).

    `analysis` supplies the OCR text boxes so the content term is the one the Score really
    uses (`content_effective`: type by the tolerant metric, the rest strict). Without it the
    board printed the raw pointwise `content_match` and disagreed with the pipeline's own
    number on every cover that has text — capa8 read 0.889 on the board and 0.9095 in the run.
    """
    import importlib.util
    import numpy as np
    from skimage.metrics import structural_similarity as ssim

    spec = importlib.util.spec_from_file_location("vc", _HERE / "visual_comparator.py")
    vc   = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vc)

    o = np.asarray(orig)
    r = np.asarray(rend)
    ss     = float(ssim(o, r, channel_axis=2, data_range=255))
    cm, iou, _tol = vc._content_metrics(o, r)
    ce = cm
    if analysis:
        cv = analysis.get("canvas", {})
        tb = vc._text_boxes_from_analysis(analysis, cv.get("width_cm", 21.0),
                                          cv.get("height_cm", 29.7), o.shape)
        tm = vc.text_match(o, r, tb)
        if tm is not None and tb:
            nt, share = vc._content_split(o, r, tb)
            if nt is None:
                ce = tm if share > 0 else cm
            elif share > 0:
                ce = (1.0 - share) * nt + share * tm
    # The Score is now ssim + structural (calibrated against the user's own labels); the
    # content terms stayed as diagnostics. Read the weights from the comparator so the board
    # can never drift from what the pipeline actually optimises.
    w = vc._SCORE_W
    score = w["ssim"] * ss + w["content_match"] * ce + w["content_iou"] * iou
    return score, ss, ce


def build_board(nums: "list[int]") -> "Path | None":
    from PIL import Image, ImageDraw

    cells = []
    for n in nums:
        orig_p = _COVERS / f"capa_teste{n}.png"
        rend_p = _OUT / f"capa_teste{n}" / "render.png"
        if not orig_p.exists() or not rend_p.exists():
            print(f"[skip] capa_teste{n}: render ausente (rode com --build)")
            continue

        orig = Image.open(orig_p).convert("RGB")
        rend = Image.open(rend_p).convert("RGB").resize(orig.size, Image.LANCZOS)
        an_p = _OUT / f"capa_teste{n}" / "analysis.json"
        an = None
        if an_p.exists():
            import json
            try:
                an = json.loads(an_p.read_text(encoding="utf-8"))
            except Exception:
                an = None
        try:
            score, ss, cm = _metrics(orig, rend, an)
            label  = f"capa{n}  Score {score:.3f}  SSIM {ss:.3f}  content {cm:.3f}"
            flag   = (0, 200, 0) if cm >= 0.7 else (230, 180, 0) if cm >= 0.4 else (230, 60, 60)
        except Exception as exc:                       # metrics optional
            label, flag = f"capa{n}  ({type(exc).__name__})", (150, 150, 150)

        sc = _THUMB_H / orig.height
        wv = int(orig.width * sc)
        o  = orig.resize((wv, _THUMB_H), Image.LANCZOS)
        r  = rend.resize((wv, _THUMB_H), Image.LANCZOS)

        lab = 24
        cell = Image.new("RGB", (wv, _THUMB_H * 2 + lab + 4), (28, 28, 28))
        cell.paste(o, (0, lab))
        cell.paste(r, (0, lab + _THUMB_H + 4))
        d = ImageDraw.Draw(cell)
        d.rectangle([0, 0, wv, lab], fill=(40, 40, 40))
        d.rectangle([0, 0, 6, lab], fill=flag)
        d.text((10, 6), label, fill=(240, 240, 240))
        cells.append(cell)

    if not cells:
        print("[!] Nada para montar — gere os renders primeiro (--build).")
        return None

    gap = 10
    W = sum(c.width for c in cells) + gap * (len(cells) - 1)
    H = max(c.height for c in cells)
    board = Image.new("RGB", (W, H), (18, 18, 18))
    x = 0
    for c in cells:
        board.paste(c, (x, 0))
        x += c.width + gap
    board.save(_BOARD)
    return _BOARD


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    do_build = "--build" in args
    nums = _discover([a for a in args if not a.startswith("--")])
    if not nums:
        print("Nenhuma capa encontrada em capas_teste/.")
        sys.exit(1)

    if do_build:
        _build(nums)

    board = build_board(nums)
    if board:
        print(f"\n[OK] Painel: {board}")
        print("Ver:  start automation\\output\\replicated\\_review_board.png")
        print("(cima = original, baixo = render; barra verde/amarela/vermelha = content_match)")
