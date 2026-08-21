"""Where does the RENDER disagree with the ORIGINAL, in big contiguous blobs?
Reports each blob's bbox in cm, its area, and what colour each side has there — so the
culprit region can be identified without modelling the draw order."""
import sys, json
import numpy as np
from PIL import Image
from scipy import ndimage

from pathlib import Path as _P
ROOT = str(_P(__file__).resolve().parents[2])   # <repo>/automation/tools/x.py
n = sys.argv[1] if len(sys.argv) > 1 else "1"
top = int(sys.argv[2]) if len(sys.argv) > 2 else 10
o = Image.open(fr"{ROOT}\capas_teste\capa_teste{n}.png").convert("RGB")
r = Image.open(fr"{ROOT}\automation\output\replicated\capa_teste{n}\render.png").convert("RGB").resize(o.size, Image.LANCZOS)
O, R = np.asarray(o).astype(int), np.asarray(r).astype(int)
hpx, wpx = O.shape[:2]
# analysis.json IS the deliverable (stage 13 writes the adopted VLM analysis back into it),
# and most covers have no VLM cache at all — so prefer it and keep vlm_analysis as fallback
_d = _P(ROOT) / "automation" / "output" / "replicated" / f"capa_teste{n}"
_an_p = next((p for p in (_d / "analysis.json", _d / "vlm_analysis.json") if p.exists()), None)
if _an_p is None:
    sys.exit(f"capa{n}: nenhum analysis.json em {_d}")
an = json.loads(_an_p.read_text(encoding="utf-8"))
W, H = an["canvas"]["width_cm"], an["canvas"]["height_cm"]

d = np.sqrt(((O - R) ** 2).sum(2))
bad = d > 70
bad = ndimage.binary_opening(bad, np.ones((5, 5)))     # ignore edge fringes / text
lbl, k = ndimage.label(bad)
print(f"capa{n}: {bad.mean()*100:.1f}% dos pixels discordam (>70 RGB), {k} manchas")
sizes = ndimage.sum(bad, lbl, range(1, k + 1))
order = np.argsort(-sizes)[:top]
print(f"\n{'area px':>8s} {'%capa':>6s} | {'bbox cm (x,y,w,h)':>28s} | original -> render")
for idx in order:
    i = int(idx) + 1
    if sizes[idx] < 400:
        break
    m = lbl == i
    ys, xs = np.where(m)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    bx = x0 / wpx * W; by = (hpx - y1) / hpx * H
    bw = (x1 - x0) / wpx * W; bh = (y1 - y0) / hpx * H
    co = O[m].mean(0).round(0).astype(int); cr = R[m].mean(0).round(0).astype(int)
    print(f"{int(sizes[idx]):8d} {sizes[idx]/(hpx*wpx)*100:5.1f}% | "
          f"({bx:5.2f},{by:5.2f},{bw:5.2f},{bh:5.2f}) | "
          f"#{co[0]:02X}{co[1]:02X}{co[2]:02X} -> #{cr[0]:02X}{cr[1]:02X}{cr[2]:02X}")
