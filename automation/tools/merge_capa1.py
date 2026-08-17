"""Merge capa1's freshly DETECTED graphics (ring sectors + mosaic tiles) into its cached
vlm_analysis.json, keeping the hand-corrected TEXT. Everything comes from the detector —
capa1 only needs this because its OCR is non-deterministic, not because it is hand-authored.
"""
import json, sys, shutil
sys.path.insert(0, r"c:\Users\itall\Downloads\versatus-template-book-v0.2.3\versatus-template-book-v0.2.3\automation\scripts")
import image_analyzer as ia

from pathlib import Path as _P
ROOT = str(_P(__file__).resolve().parents[2])   # <repo>/automation/tools/x.py
CACHE = fr"{ROOT}\automation\output\replicated\capa_teste1\vlm_analysis.json"
BASE = CACHE + ".bak"          # the pre-ring cache: the approved TEXT, original graphics

an = json.load(open(BASE, encoding="utf-8"))
W, H = an["canvas"]["width_cm"], an["canvas"]["height_cm"]
fresh = ia.analyze_image(fr"{ROOT}\capas_teste\capa_teste1.png", canvas_w_cm=W, canvas_h_cm=H)
sectors = [r for r in fresh["regions"] if r.get("shape_type") == "annulus_sector"]
mosaic = [r for r in fresh["regions"] if r.get("source") == "mosaic"]
print(f"detector: {len(sectors)} setores de anel, {len(mosaic)} peças de mosaico")
if not sectors:
    sys.exit("sem setores — abortando")

# Take the detector's REGIONS wholesale — the cache only exists because capa1's OCR is
# non-deterministic (its TEXT), not because its graphics are hand-made. Regions the VLM
# added (a rule, etc.) are carried over since the fresh run has no VLM stage.
vlm_regions = [r for r in an["regions"] if r.get("source") == "vlm"]
an["regions"] = list(fresh["regions"]) + vlm_regions
print(f"regioes: {len(fresh['regions'])} do detector + {len(vlm_regions)} do VLM")
shutil.copy(CACHE, CACHE + ".prev")
json.dump(an, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"ok -> {len(an['regions'])} regioes, {len(an['text_elements'])} textos (do cache)")
