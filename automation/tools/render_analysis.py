"""Render + measure ANY analysis json with the real pipeline machinery (tikz → LuaLaTeX →
PNG → compare). Used to score the vectoriser against the detector stack on equal terms."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # <repo>/automation/tools/render_analysis.py
sys.path.insert(0, str(ROOT / "automation" / "scripts"))
import importlib.util


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "automation" / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rc = _load("replicate_cover")
tg = _load("tikz_generator")
vc = _load("visual_comparator")

n = sys.argv[1]
src = sys.argv[2] if len(sys.argv) > 2 else "vec_analysis.json"
tag = sys.argv[3] if len(sys.argv) > 3 else "vec"

cover_dir = ROOT / "automation" / "output" / "replicated" / f"capa_teste{n}"
image = ROOT / "capas_teste" / f"capa_teste{n}.png"
a = json.loads((cover_dir / src).read_text(encoding="utf-8"))
W = a["canvas"]["width_cm"]; H = a["canvas"]["height_cm"]

tikz = cover_dir / f"{tag}.tikz"; tex = cover_dir / f"{tag}.tex"
pdf = cover_dir / f"{tag}.pdf"; png = cover_dir / f"{tag}.png"
tg.generate(a, tikz)
rc._write_tex_wrapper(tex, tikz, a, W, H)
ok, err = rc._compile_lualatex(tex, pdf)
if not ok:
    print("FALHA no LuaLaTeX:", err[:400]); sys.exit(1)
if rc._render_pdf(pdf, png, 150) is None:
    print("FALHA no render"); sys.exit(1)
q = vc.compare(str(image), str(png), analysis=a, output_dir=cover_dir, ssim_threshold=0.95)
print(f"capa{n} [{src}] Score={q['score']:.4f}  SSIM={q['ssim_global']:.4f}  "
      f"content={q.get('content_match',0):.3f}  IoU={q.get('content_iou',0):.3f}  -> {png.name}")
