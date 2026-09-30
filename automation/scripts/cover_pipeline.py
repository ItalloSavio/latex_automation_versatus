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
            →  o LIVRO           →  build/pdf/main.pdf           (a capa dentro do livro,
                                                                  so com --livro)

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


def _load_tool(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "automation" / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _compile_book(log_path):
    """latexmk como o Makefile faz; o latexmkrc manda a saida para build/pdf/."""
    import shutil                                       # noqa: PLC0415
    import subprocess                                   # noqa: PLC0415
    if not shutil.which("latexmk"):
        return None, "latexmk nao encontrado no PATH"
    with open(log_path, "w", encoding="utf-8") as fh:
        p = subprocess.run(["latexmk", "-lualatex", "-interaction=nonstopmode",
                            "-halt-on-error", "main.tex"],
                           cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT)
    pdf = ROOT / "build" / "pdf" / "main.pdf"
    return (pdf if p.returncode == 0 and pdf.exists() else None), f"latexmk saiu com {p.returncode}"


def run(image, brand="versatus", out_dir=None, rebuild=False, recompose=False,
        vlm=False, max_passes=3, dpi=None, integrate=False, book=False):
    integrate = integrate or book                       # o livro precisa da capa integrada
    total = 1 + integrate + book
    img = Path(image).resolve()
    if not img.exists():
        print(f"[erro] imagem nao encontrada: {img}")
        return 2

    d = Path(out_dir).resolve() if out_dir else (
        ROOT / "automation" / "output" / "replicated" / img.stem)
    analysis = d / "analysis.json"
    if out_dir and d.name != img.stem:
        # O replicador grava em <pai>/<nome-da-imagem>. Com outro nome a replica inteira rodava
        # e so no fim o comando acusava "nao produziu analysis.json" (achado em 30/09).
        print(f"[erro] --out-dir precisa terminar no nome da imagem: use {d.parent / img.stem}")
        return 2

    # ── 1. replica ────────────────────────────────────────────────────────────
    rc = None
    if analysis.exists() and not rebuild:
        shown = analysis.relative_to(ROOT) if analysis.is_relative_to(ROOT) else analysis
        print(f"[1/{total}] replica: reusando {shown} (--rebuild para refazer)")
    else:
        print(f"[1/{total}] replica: rodando o pipeline sobre {img.name}")
        rc = _load("replicate_cover")
        rc.replicate(str(img), out_dir=str(d.parent), max_passes=max_passes,
                     dpi=dpi, vlm=vlm)
        if not analysis.exists():
            print("[erro] o replicador nao produziu analysis.json")
            return 1

    # ── veredito da replica ───────────────────────────────────────────────────
    # O Score diz quanto a replica se parece com o original; nao diz se ela esta QUEBRADA, e
    # e justamente onde ele e cego que os defeitos moram. Ver automation/tools/accept.py.
    try:
        import json as _json                            # noqa: PLC0415
        acc = _load_tool("accept")
        an = _json.loads(analysis.read_text(encoding="utf-8"))
        found = acc.check(an)
        # A AUSENCIA e a metade que o `check` sozinho nao ve: olhando so a analise final, nao ha
        # como saber o que sumiu. O `reference.json` (escrito pelo assembler no estagio 1) e a
        # unica leitura do original que nenhum portao tocou — sem ele o veredito fica cego a
        # meio titulo faltando, que foi exatamente como a capa19 saiu aprovada.
        ref_p = acc.reference_for(d)
        if ref_p:
            found += acc.reference_findings(
                an, _json.loads(ref_p.read_text(encoding="utf-8")), img, d / "render.png")
        else:
            print("  [aviso] sem reference.json — AUSENCIA nao verificada "
                  "(rode com --rebuild para gera-lo)")
        v = acc.verdict(found)
        print(f"\n  veredito    : {v}")
        for lv, msg in found:
            print(f"    [{lv}] {msg}")
        if rc is not None:                              # o veredito vai para o _progresso.md
            rc.progress_note([f"**Veredito do portao de aceite: {v}**", ""]
                             + [f"- [{lv}] {msg}" for lv, msg in found])
    except Exception as exc:                            # nunca quebrar a rodada por causa disto
        print(f"  veredito    : indisponivel ({type(exc).__name__})")

    # ── 2. conteudo do livro — OPCIONAL ───────────────────────────────────────
    # Replicar a imagem e o objetivo; trocar o conteudo pelo do livro e um segundo passo que
    # so acontece quando pedido. Sem --integrar o comando entrega a replica e para.
    if not integrate:
        print(f"\n  replica     : {d / 'render.png'}")
        print(f"  pdf         : {d / 'cover.pdf'}")
        print("  (--integrar para compor o conteudo do livro por cima)")
        return 0

    print(f"[2/{total}] composicao: {brand}")
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
    if not book:
        print("  (--livro para colocar esta capa no livro e compila-lo)")
        return 0

    # ── 3. a capa DENTRO do livro — OPCIONAL (E1) ─────────────────────────────
    # styles/versatus-dynamic-cover.tex e o que o main.tex carrega; o arquivo substituido vai
    # para automation/output/_backup_livro/ antes. Ver cover_integrator.book_cover_tex.
    if pen > 0:
        print(f"\n  [aviso] a composicao tem penalidade {pen} — confira a capa final antes de "
              f"publicar o livro")
    print(f"\n[3/{total}] livro: instalando a capa e compilando main.tex (latexmk, ~3 min)")
    inst = ci.install_in_book(d, brand=brand)
    print(f"  capa do livro : {inst['dst'].relative_to(ROOT)}")
    if inst["backup"]:
        print(f"  a anterior    : {inst['backup'].relative_to(ROOT)}")
    pdf, msg = _compile_book(d / "livro_latexmk.log")
    if pdf is None:
        print(f"[erro] o livro nao compilou ({msg}) — log em {d / 'livro_latexmk.log'}")
        return 1
    print(f"  livro         : {pdf}")
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
    p.add_argument("--livro", dest="book", action="store_true",
                   help="integra, poe a capa no livro (styles/versatus-dynamic-cover.tex, com "
                        "backup da anterior) e compila main.tex")
    p.add_argument("--recompose", action="store_true",
                   help="recompoe e guarda no cache de arte se a penalidade melhorar "
                        "(entrada com \"locked\": true nunca e sobrescrita)")
    p.add_argument("--vlm", action="store_true", help="passe do VLM na replica")
    # 3, nao 1 (pipeline-ideal.md §4.5). Com o laco antigo, max_passes=1 significava ZERO
    # correcoes: a renderizacao inicial contava como passada e o laco quebrava antes de
    # propor — o calibrador ficou inerte nas 9 capas do MVP. Agora conta RODADAS DE
    # PROPOSTA, e o laco para sozinho quando uma rodada nao aceita nada. Tempo nao e
    # restricao neste projeto; nao reduza para "ser rapido".
    p.add_argument("--max-passes", type=int, default=3,
                   help="rodadas de correcao (para antes se uma rodada nao aceita nada)")
    p.add_argument("--dpi", type=int, default=None,
                   help="dpi do render (default: o da imagem-fonte, nunca abaixo de 150)")
    a = p.parse_args(argv)
    return run(a.image, brand=a.brand, out_dir=a.out_dir, rebuild=a.rebuild,
               recompose=a.recompose, vlm=a.vlm, max_passes=a.max_passes, dpi=a.dpi,
               integrate=a.integrate, book=a.book)


if __name__ == "__main__":
    # line_buffering: com stdout num pipe o Python bufferiza em bloco e o progresso so
    # aparecia no fim da rodada. Ver replicate_cover._Progress.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.exit(main())
