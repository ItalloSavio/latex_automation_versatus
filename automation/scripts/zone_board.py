#!/usr/bin/env python3
"""
zone_board.py — de-average the Score: WHERE is a cover wrong, by zone?

The global content_match hides *where* the error lives — a big mosaic error can swamp a
text fix, so the single number can't tell you whether the fix helped (this is exactly
what made the angular-sector attempt look flat: the target is only ~9% of the area).
This splits the cover into a grid, scores content_match per cell against the GLOBAL
background, and ranks cells by `error × area` = the biggest weighted offenders. The
per-cell errors sum back to the global content deficit, so the ranking says precisely
where fixing content would help the global metric most.

Use it to (a) route effort to the worst zone and (b) see a LOCAL win the global number
can't show (compare a zone's content_match before/after a change).

Usage:
    python automation/scripts/zone_board.py 1            # capa1, default 6x4 grid
    python automation/scripts/zone_board.py 1 8x4        # custom grid
    python automation/scripts/zone_board.py 1 6 7        # several covers

Output per cover: a ranked print of the worst zones (+ ESQ/DIR, TOPO/BASE halves) and a
heatmap automation/output/replicated/capa_testeN/zones.png (render tinted by error×area).
The metric primitives come from visual_comparator — single source of truth.
"""

import importlib.util
import re
import sys
from pathlib import Path

_HERE   = Path(__file__).resolve().parent
_ROOT   = _HERE.parent.parent
_COVERS = _ROOT / "capas_teste"
_OUT    = _HERE.parent / "output" / "replicated"


def _vc():
    spec = importlib.util.spec_from_file_location("vc", _HERE / "visual_comparator.py")
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def zone_scores(orig, rend, rows, cols, vc):
    """Per-cell (content_match, foreground count, error×area).

    Background is GLOBAL (from the original) so an all-content cell still measures
    against the true background. Same foreground/match thresholds as _content_metrics,
    so sum(fg·(1-cm)) over cells = the global content deficit."""
    import numpy as np
    o = orig.astype(int)
    r = rend.astype(int)
    bg = vc._background_color(orig)
    H, W = o.shape[:2]

    fg    = (np.sqrt(((o - bg) ** 2).sum(2)) > vc._CONTENT_BG_DIST) | \
            (np.sqrt(((r - bg) ** 2).sum(2)) > vc._CONTENT_BG_DIST)
    match = np.sqrt(((o - r) ** 2).sum(2)) < vc._CONTENT_MATCH_D

    cells = []
    for i in range(rows):
        for j in range(cols):
            y0, y1 = i * H // rows, (i + 1) * H // rows
            x0, x1 = j * W // cols, (j + 1) * W // cols
            m = fg[y0:y1, x0:x1]
            n = int(m.sum())
            cm = float(match[y0:y1, x0:x1][m].mean()) if n else 1.0
            cells.append({"i": i, "j": j, "cm": cm, "fg": n,
                          "fg_frac": n / m.size, "err": n * (1.0 - cm),
                          "box": (x0, y0, x1, y1)})
    return cells


def run(n, rows, cols, vc):
    from PIL import Image, ImageDraw
    import numpy as np

    op = _COVERS / f"capa_teste{n}.png"
    rp = _OUT / f"capa_teste{n}" / "render.png"
    if not op.exists() or not rp.exists():
        print(f"[skip] capa{n}: faltam imagens (rode replicate_cover primeiro)")
        return

    orig = Image.open(op).convert("RGB")
    rend = Image.open(rp).convert("RGB").resize(orig.size, Image.LANCZOS)
    cells = zone_scores(np.asarray(orig), np.asarray(rend), rows, cols, vc)
    total = sum(c["err"] for c in cells) or 1.0

    print(f"\n=== capa{n}  grade {rows}x{cols}  (zonas PIORES primeiro) ===")
    print(f"{'zona':6} {'content':>8} {'fg%':>6} {'erro×área':>10} {'% do erro':>9}")
    for c in sorted(cells, key=lambda c: -c["err"])[:8]:
        print(f"r{c['i']}c{c['j']:<3} {c['cm']:8.3f} {100*c['fg_frac']:6.1f} "
              f"{c['err']:10.0f} {100*c['err']/total:8.1f}%")

    half = lambda pred: 100 * sum(c["err"] for c in cells if pred(c)) / total
    print(f"  metades:  ESQ {half(lambda c: c['j'] <  cols/2):.0f}%"
          f" | DIR {half(lambda c: c['j'] >= cols/2):.0f}%"
          f"   ||   TOPO {half(lambda c: c['i'] <  rows/2):.0f}%"
          f" | BASE {half(lambda c: c['i'] >= rows/2):.0f}%")

    heat = rend.copy()
    draw = ImageDraw.Draw(heat, "RGBA")
    mx = max(c["err"] for c in cells) or 1.0
    for c in cells:
        x0, y0, x1, y1 = c["box"]
        draw.rectangle([x0, y0, x1 - 1, y1 - 1],
                       fill=(255, 0, 0, int(170 * c["err"] / mx)),
                       outline=(255, 255, 255, 70))
    out = _OUT / f"capa_teste{n}" / "zones.png"
    heat.save(out)
    print(f"  heatmap: {out}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows, cols, nums = 6, 4, []
    for a in sys.argv[1:]:
        if re.fullmatch(r"\d+x\d+", a):
            rows, cols = map(int, a.split("x"))
        elif a.isdigit():
            nums.append(int(a))
    vc = _vc()
    for n in (nums or [1]):
        run(n, rows, cols, vc)
