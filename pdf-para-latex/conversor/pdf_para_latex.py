"""Converte um PDF digital em LaTeX editável e compila de volta para PDF.

    python pdf-para-latex/conversor/pdf_para_latex.py pdf-para-latex/entrada/arquivo.pdf

Saída em pdf-para-latex/saida/<nome>/:
    <nome>.tex          o conteúdo (edite aqui)
    estilo.sty          o desenho medido: fontes, tamanhos, cores, cabeçalho
    diagramacao.sty     a biblioteca de componentes (igual para todo documento)
    <nome>.pdf          o PDF compilado
    espacos-de-imagem/  recorte do original para cada imagem a colocar + LISTA.md
    comparacao/         original x gerado, página a página + relatorio.md
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import fitz  # noqa: E402

from analisar import analisar  # noqa: E402
from extrair import extrair  # noqa: E402
from gerar import Gerador  # noqa: E402

JOB = AQUI.parent


def _passo(t0, msg):
    print(f"[{time.time() - t0:5.1f}s] {msg}", flush=True)


def _recortes(doc_pdf: fitz.Document, espacos, pasta: Path):
    pasta.mkdir(parents=True, exist_ok=True)
    for velho in pasta.glob("*.png"):      # recortes de uma rodada anterior
        velho.unlink()
    linhas = ["# Espaços de imagem", "",
              "Cada espaço tem um NOME. Salve o arquivo com esse nome em `pdf-para-latex/imagens/`",
              "(`.pdf` para vetor, ou `.png`/`.jpg` com 300 dpi ou mais) e compile de novo.",
              "O recorte do original ao lado de cada nome mostra o que vai ali.", "",
              "| nome | página | largura × altura (bp) | largura × altura (mm) | o que é |",
              "|---|---|---|---|---|"]
    tipos = {"imagem": "imagem (raster) no fluxo", "figura": "diagrama/figura vetorial no fluxo",
             "grafismo": "grafismo em posição fixa (pode sangrar)"}
    for e in espacos:
        pg = doc_pdf[e.pagina - 1]
        clip = fitz.Rect(e.x0, e.y0, e.x1, e.y1) & pg.rect
        pix = pg.get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip)
        pix.save(str(pasta / f"{e.nome}.png"))
        w, h = e.x1 - e.x0, e.y1 - e.y0
        linhas.append(f"| `{e.nome}` | {e.pagina} | {w:.1f} × {h:.1f} | {w * 0.3528:.1f} × {h * 0.3528:.1f} | "
                      f"{tipos[e.tipo]} — ![{e.nome}]({e.nome}.png) |")
    (pasta / "LISTA.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")


def _assinatura(pasta: Path, nome: str) -> str:
    import hashlib
    h = hashlib.sha256()
    for arq in (pasta / f"{nome}.tex", pasta / "estilo.sty"):
        if arq.exists():
            h.update(arq.read_bytes())
    return h.hexdigest()


def compilar(pasta: Path, nome: str) -> tuple[bool, str]:
    build = pasta / "build"
    build.mkdir(exist_ok=True)
    cmd = ["lualatex", "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={build}", f"{nome}.tex"]
    r = subprocess.run(cmd, cwd=pasta, capture_output=True, text=True, encoding="utf-8", errors="replace")
    pdf = build / f"{nome}.pdf"
    if r.returncode != 0 or not pdf.exists():
        log = (build / f"{nome}.log")
        trecho = log.read_text(encoding="utf-8", errors="replace")[-3000:] if log.exists() else r.stdout[-3000:]
        return False, trecho
    shutil.copy(pdf, pasta / f"{nome}.pdf")
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", help="PDF de entrada (digital, com texto)")
    ap.add_argument("--saida", help="pasta de saída (padrão: pdf-para-latex/saida/<nome>)")
    ap.add_argument("--sem-compilar", action="store_true", help="só gera o LaTeX")
    ap.add_argument("--sem-comparar", action="store_true", help="não gera a comparação com o original")
    ap.add_argument("--so-compilar", action="store_true",
                    help="não gera nada: recompila o .tex que já está na saída (use depois de editar)")
    ap.add_argument("--sobrescrever", action="store_true",
                    help="gera de novo mesmo que o .tex/estilo.sty tenham sido editados à mão")
    a = ap.parse_args()

    t0 = time.time()
    origem = Path(a.pdf).resolve()
    nome = origem.stem
    pasta = Path(a.saida).resolve() if a.saida else JOB / "saida" / nome
    pasta.mkdir(parents=True, exist_ok=True)
    marca = pasta / "build" / "gerado.sha256"

    if a.so_compilar:
        _passo(t0, "compilando o .tex existente")
        ok, log = compilar(pasta, nome)
        if not ok:
            print("ERRO na compilação. Final do log:\n" + log)
            sys.exit(1)
        print(f"        {pasta / (nome + '.pdf')}")
        if not a.sem_comparar:
            from comparar import comparar
            print(comparar(origem, pasta / f"{nome}.pdf", pasta / "comparacao"))
        return

    # não apaga edição feita à mão
    if marca.exists() and not a.sobrescrever and _assinatura(pasta, nome) != marca.read_text():
        print(f"PARADO: {nome}.tex ou estilo.sty foram editados depois de gerados.\n"
              f"  Para recompilar a sua versão:  --so-compilar\n"
              f"  Para gerar de novo e PERDER as edições:  --sobrescrever")
        sys.exit(2)
    _passo(t0, f"1/5 lendo {origem.name}")
    paginas, medidor, doc_pdf = extrair(str(origem))
    _passo(t0, f"2/5 analisando {len(paginas)} página(s)")
    doc = analisar(paginas, medidor)
    print(f"        estilos: " + ", ".join(f"{e.nome} {e.tamanho:g}/{e.entrelinha:g}" for e in doc.estilos))
    print(f"        espaços de imagem: {len(doc.espacos_imagem)}  ·  quadros: "
          + ", ".join(f"p{p.numero}={len(p.quadros)}" for p in doc.paginas))
    for av in doc.avisos:
        print(f"        aviso: {av}")

    _passo(t0, "3/5 escrevendo o LaTeX")
    g = Gerador(doc, origem.name)
    (pasta / "estilo.sty").write_text(g.estilo_sty(), encoding="utf-8")
    (pasta / f"{nome}.tex").write_text(g.documento_tex(), encoding="utf-8")
    shutil.copy(AQUI / "latex" / "diagramacao.sty", pasta / "diagramacao.sty")
    marca.parent.mkdir(exist_ok=True)
    marca.write_text(_assinatura(pasta, nome))
    _recortes(doc_pdf, doc.espacos_imagem, pasta / "espacos-de-imagem")
    print(f"        {pasta / (nome + '.tex')}")

    if a.sem_compilar:
        return
    _passo(t0, "4/5 compilando com LuaLaTeX")
    ok, log = compilar(pasta, nome)
    if not ok:
        print("ERRO na compilação. Final do log:\n" + log)
        sys.exit(1)
    print(f"        {pasta / (nome + '.pdf')}")

    if a.sem_comparar:
        return
    _passo(t0, "5/5 comparando com o original")
    from comparar import comparar
    resumo = comparar(origem, pasta / f"{nome}.pdf", pasta / "comparacao", doc.espacos_imagem)
    print(resumo)
    _passo(t0, "pronto")


if __name__ == "__main__":
    main()
