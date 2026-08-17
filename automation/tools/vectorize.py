"""EXPERIMENT — a GENERAL vectoriser instead of one detector per shape.

Swiss design is flat colour regions with hard edges: the best possible case for contour
tracing. Quantise to the measured palette, take each colour's mask, trace its contours,
simplify, and emit them as POLYGONS — a primitive `_cmd_polygon` already renders.

If this beats the hand-written detector stack on the 7 covers, the whole "vocabulary gap"
category disappears for graphics and the dev stops being in the loop.

Usage:  python vectorize.py <n> [eps_frac] [min_area_frac]
Writes  <cover_dir>/vec_analysis.json  and prints the region count.
"""
import json, sys, math
import numpy as np
import cv2
from PIL import Image

from pathlib import Path as _P
ROOT = str(_P(__file__).resolve().parents[2])   # <repo>/automation/tools/x.py
sys.path.insert(0, fr"{ROOT}\automation\scripts")
import image_analyzer as ia

n = sys.argv[1]
EPS = float(sys.argv[2]) if len(sys.argv) > 2 else 0.004   # simplification, × perimeter
MIN_A = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0004  # drop specks below this share

img = Image.open(fr"{ROOT}\capas_teste\capa_teste{n}.png").convert("RGB")
arr = np.asarray(img).astype(int)
h_px, w_px = arr.shape[:2]
w_cm = 21.0
h_cm = round(w_cm * h_px / w_px, 2)

colors = ia._extract_colors(img)
pal = np.array([c["rgb"] for c in colors], float)
hexes = [c["hex"] for c in colors]
bg_hex = hexes[0]
print(f"capa{n}: {w_px}x{h_px}  paleta={hexes}")

# quantise every pixel to its nearest palette entry
lab = ((arr.reshape(-1, 1, 3) - pal[None, :, :]) ** 2).sum(2).argmin(1).reshape(h_px, w_px)

def to_cm(pts):
    return [[round(float(x) / w_px * w_cm, 3), round((h_px - float(y)) / h_px * h_cm, 3)]
            for x, y in pts]

regions = []
for ci, hexc in enumerate(hexes):
    if hexc == bg_hex:
        continue                              # the page already carries the background
    mask = (lab == ci).astype(np.uint8)
    if mask.sum() < MIN_A * h_px * w_px:
        continue
    # close 1px gaps so anti-aliased seams don't shatter a region
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        a = cv2.contourArea(c)
        if a < MIN_A * h_px * w_px:
            continue
        approx = cv2.approxPolyDP(c, EPS * cv2.arcLength(c, True), True)
        pts = to_cm(approx.reshape(-1, 2))
        if len(pts) < 3:
            continue
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        regions.append({
            "color_hex": hexc, "shape_type": "polygon", "points_cm": pts,
            "bbox_cm": {"x": min(xs), "y": min(ys),
                        "w": max(xs) - min(xs), "h": max(ys) - min(ys)},
            "area_pct": round(a / (h_px * w_px), 5), "source": "vector",
        })

regions.sort(key=lambda r: -r["area_pct"])     # big first → painter's algorithm
print(f"   {len(regions)} poligonos  (vertices: {sum(len(r['points_cm']) for r in regions)})")

out = {
    "canvas": {"width_cm": w_cm, "height_cm": h_cm, "format": "A4"},
    "colors": colors,
    "background_color": bg_hex,
    "regions": regions,
    "text_elements": [],
}
dst = fr"{ROOT}\automation\output\replicated\capa_teste{n}\vec_analysis.json"
json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"   -> {dst}")
