"""Does the analysis.json on disk still reproduce the render.png we shipped?

This catches the most expensive bug family in the project: the pipeline decides one thing
and the deliverable receives another (the plateau branch breaking without re-rendering, a
cached analysis loaded back as a finished answer, the winning analysis only persisted
inside the loop). The class is SILENT by construction — the reported number goes up, the
file on disk lies, and nobody notices. So we re-render every stored analysis with the real
machinery and compare its Score against the Score of the PNG that is actually on disk.

  python automation/tools/audit.py            # all covers
  python automation/tools/audit.py 3 16 18    # only these

A non-zero delta means the two DIVERGE — it does NOT say which side is right. Re-run the
cover to find out. (I read this backwards once: I concluded "the number was lying upward"
when it was the JSON that held the worse version.)
"""
import json, sys, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation" / "scripts"))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "automation" / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rc = _load("replicate_cover")
tg = _load("tikz_generator")
vc = _load("visual_comparator")

OUT = ROOT / "automation" / "output" / "replicated"
_TOL = 1e-4                      # below this the two renders are the same picture


def _score(image, png, analysis, cover_dir):
    q = vc.compare(str(image), str(png), analysis=analysis, output_dir=cover_dir,
                   ssim_threshold=0.95)
    return q["score"]


def audit(n):
    cover_dir = OUT / f"capa_teste{n}"
    image = ROOT / "capas_teste" / f"capa_teste{n}.png"
    aj, shipped = cover_dir / "analysis.json", cover_dir / "render.png"
    if not (aj.exists() and shipped.exists() and image.exists()):
        return n, None, None, "faltam arquivos"

    a = json.loads(aj.read_text(encoding="utf-8"))
    disk = _score(image, shipped, a, cover_dir)

    # Re-render that same analysis from scratch, with the real tikz → LuaLaTeX → PNG path.
    tikz, tex = cover_dir / "audit.tikz", cover_dir / "audit.tex"
    pdf, png = cover_dir / "audit.pdf", cover_dir / "audit.png"
    W, H = a["canvas"]["width_cm"], a["canvas"]["height_cm"]
    tg.generate(a, tikz)
    rc._write_tex_wrapper(tex, tikz, a, W, H)
    ok, err = rc._compile_lualatex(tex, pdf)
    if not ok:
        return n, disk, None, f"LuaLaTeX falhou: {err[:120]}"
    if rc._render_pdf(pdf, png, 150) is None:
        return n, disk, None, "render falhou"
    fresh = _score(image, png, a, cover_dir)
    return n, disk, fresh, None


def main(argv):
    nums = [int(x) for x in argv] if argv else sorted(
        int("".join(c for c in p.name if c.isdigit())) for p in OUT.glob("capa_teste*"))
    print(f"{'capa':>6} {'em disco':>9} {'re-render':>10} {'delta':>9}  veredito")
    bad = 0
    for n in nums:
        n, disk, fresh, err = audit(n)
        if err:
            print(f"{n:>6} {'-':>9} {'-':>10} {'-':>9}  ERRO: {err}")
            bad += 1
            continue
        d = fresh - disk
        verdict = "ok" if abs(d) <= _TOL else "DIVERGE — re-rodar esta capa"
        bad += abs(d) > _TOL
        print(f"{n:>6} {disk:>9.4f} {fresh:>10.4f} {d:>+9.4f}  {verdict}")
    print(f"\n{len(nums) - bad}/{len(nums)} reproduzem o entregavel.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
