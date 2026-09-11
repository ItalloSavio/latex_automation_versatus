#!/usr/bin/env python3
"""
cover_pipeline.py — uma imagem de capa entra, a replica em TikZ sai.

    python automation/scripts/cover_pipeline.py capas_teste/capa_teste8.png

O replicador (`replicate_cover.py`) sempre aceitou um caminho qualquer, mas a segunda
metade — trocar o conteudo do poster pelo do livro — so sabia trabalhar sobre o corpus de
teste: `cover_integrator.build(n)` montava o caminho a partir de um NUMERO. Entao nao havia
comando que levasse um PNG arbitrario ate a capa final. Este e esse comando, e ele so
encadeia o que ja existe:

    imagem  →  replicate_cover   →  analysis.json + render.png   (a REPLICA — o objetivo)
            →  cover_integrator  →  integrated.pdf / .png        (o conteudo do LIVRO,
                                                                  so com --integrar)

A REPLICA e o produto. Trocar o texto do poster pelo do livro e um segundo passo opcional, e
quando ele roda a direcao de arte pode ser fixada a mao: `automation/art/<nome>.json` guarda
a posicao da marca e de cada bloco, e uma entrada com `"locked": true` nunca e sobrescrita
pela composicao automatica.

Duas economias, porque uma rodada completa leva minutos:
  · a etapa de replica e PULADA quando ja existe `analysis.json` para aquela imagem
    (`--rebuild` forca). E a cara: OCR mais uma dezena de compilacoes.
  · a composicao e lida do CACHE DE ARTE quando ha entrada para aquela imagem
    (`--recompose` recompoe e fica com a de menor penalidade de layout).

Saidas, todas em `automation/output/replicated/<nome-da-imagem>/`:
    render.png / cover.pdf          a replica do poster
    integrated.png / integrated.pdf a capa com o conteudo de config/metadata.tex
    integrated_analysis.json        o que foi desenhado, para auditoria
"""

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "automation" / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(image, brand="versatus", out_dir=None, rebuild=False, recompose=False,
        vlm=False, max_passes=1, dpi=150, integrate=False):
    img = Path(image).resolve()
    if not img.exists():
        print(f"[erro] imagem nao encontrada: {img}")
        return 2

    d = Path(out_dir).resolve() if out_dir else (
        ROOT / "automation" / "output" / "replicated" / img.stem)
    analysis = d / "analysis.json"

    # ── 1. replica ────────────────────────────────────────────────────────────
    if analysis.exists() and not rebuild:
        print(f"[1/2] replica: reusando {analysis.relative_to(ROOT)} (--rebuild para refazer)")
    else:
        print(f"[1/2] replica: rodando o pipeline sobre {img.name}")
        rc = _load("replicate_cover")
        rc.replicate(str(img), out_dir=str(d.parent), max_passes=max_passes,
                     dpi=dpi, vlm=vlm)
        if not analysis.exists():
            print("[erro] o replicador nao produziu analysis.json")
            return 1

    # ── 2. conteudo do livro — OPCIONAL ───────────────────────────────────────
    # Replicar a imagem e o objetivo; trocar o conteudo pelo do livro e um segundo passo que
    # so acontece quando pedido. Sem --integrar o comando entrega a replica e para.
    if not integrate:
        print(f"\n  replica     : {d / 'render.png'}")
        print(f"  pdf         : {d / 'cover.pdf'}")
        print("  (--integrar para compor o conteudo do livro por cima)")
        return 0

    print(f"[2/2] composicao: {brand}")
    ci = _load("cover_integrator")
    res = ci.build_from_image(img, brand=brand, out_dir=d, recompose=recompose)
    if not res.get("ok"):
        print(f"[erro] {res.get('error', 'falha na composicao')}")
        return 1

    pen, parts = res["penalty"], res["penalty_parts"]
    print(f"\n  arte        : {res['art']} {res['art_note']}")
    print(f"  penalidade  : {pen}   "
          f"(sobreposicao {parts['overlap']} · fora da pagina {parts['overflow']} · "
          f"contraste {parts['contrast']} · logo {parts['logo']} · "
          f"fundo do logo {parts['logo_ground']} · tamanho do logo {parts['logo_size']})")
    print(f"  replica     : {d / 'render.png'}")
    print(f"  capa final  : {res['pdf']}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Replica uma capa a partir da imagem; --integrar compoe o conteudo do livro.")
    p.add_argument("image", help="PNG/JPEG da capa a replicar")
    p.add_argument("--brand", default="versatus", help="marca em brands/ (default: versatus)")
    p.add_argument("--out-dir", default=None, help="diretorio de saida")
    p.add_argument("--rebuild", action="store_true",
                   help="refaz a replica mesmo havendo analysis.json")
    p.add_argument("--integrar", "--integrate", dest="integrate", action="store_true",
                   help="tambem compoe o conteudo do livro por cima (Fase 7, opcional)")
    p.add_argument("--recompose", action="store_true",
                   help="recompoe e guarda no cache de arte se a penalidade melhorar "
                        "(entrada com \"locked\": true nunca e sobrescrita)")
    p.add_argument("--vlm", action="store_true", help="passe do VLM na replica")
    p.add_argument("--max-passes", type=int, default=1)
    p.add_argument("--dpi", type=int, default=150)
    a = p.parse_args(argv)
    return run(a.image, brand=a.brand, out_dir=a.out_dir, rebuild=a.rebuild,
               recompose=a.recompose, vlm=a.vlm, max_passes=a.max_passes, dpi=a.dpi,
               integrate=a.integrate)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
