"""Etapa 5 — mede o PDF gerado contra o original.

Três medidas, todas fora dos espaços de imagem (lá o original tem desenho e o gerado tem
um espaço reservado):
  * palavras: cada palavra do original casada com a mesma palavra no gerado, e o quanto
    ela andou (em bp);
  * linhas: quantas linhas do original existem IGUAIS no gerado (mesma quebra de linha);
  * pixels: sobreposição visual por página — vermelho = só no original, azul = só no gerado.
"""
from __future__ import annotations

import statistics
import sys
from collections import defaultdict
from pathlib import Path

import fitz
import numpy as np

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))


def _dentro(r, areas):
    cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
    return any(a[0] - 1 <= cx <= a[2] + 1 and a[1] - 1 <= cy <= a[3] + 1 for a in areas)


def _palavras(pg, areas):
    """Palavras com a posição TIPOGRÁFICA: origem do 1º caractere (x) e linha de base (y).
    A caixa da palavra não serve: cada versão da fonte declara ascendente/descendente diferente."""
    saida = []
    for b in pg.get_text("rawdict")["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                atual, x, y, caixa = "", None, None, None
                for ch in s["chars"] + [{"c": " ", "origin": (0, 0), "bbox": (0, 0, 0, 0)}]:
                    if ch["c"].isspace():
                        if atual and not _dentro(caixa, areas):
                            saida.append((atual, x, y))
                        atual = ""
                        continue
                    if not atual:
                        x, y, caixa = ch["origin"][0], ch["origin"][1], ch["bbox"]
                    atual += ch["c"]
    return saida


def _linhas(pg, areas):
    """Linhas VISUAIS: pedaços na mesma linha de base e próximos (ex.: o '•' e o texto do item)
    são uma linha só — cada gerador de PDF os separa de um jeito."""
    pedacos = []
    for b in pg.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            t = " ".join("".join(s["text"] for s in ln["spans"]).split())
            if t and not _dentro(ln["bbox"], areas):
                pedacos.append([t, list(ln["bbox"]), ln["spans"][0]["origin"][1]])
    pedacos.sort(key=lambda p: (round(p[2]), p[1][0]))
    saida = []
    for t, r, base in pedacos:
        if saida and abs(saida[-1][2] - base) < 0.8 and 0 <= r[0] - saida[-1][1][2] < 16:
            saida[-1][0] += " " + t
            saida[-1][1][2] = r[2]
        else:
            saida.append([t, r, base])
    return [(t, r) for t, r, _ in saida]


def _cinza(pg, zoom):
    pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()


def comparar(original: Path, gerado: Path, pasta: Path, espacos=None) -> str:
    pasta.mkdir(parents=True, exist_ok=True)
    a, b = fitz.open(str(original)), fitz.open(str(gerado))
    areas_pag = defaultdict(list)
    for e in espacos or []:
        areas_pag[e.pagina].append((e.x0, e.y0, e.x1, e.y1))

    rel = ["# Comparação: original × gerado", "",
           f"- original: `{original.name}`", f"- gerado: `{gerado.name}`", "",
           "Medido fora dos espaços de imagem. **Deslocamento** = quanto cada palavra andou em relação ao "
           "original (bp; 1 bp = 0,35 mm). **Linhas iguais** = linhas com o mesmo texto e a mesma quebra.", "",
           "| página | palavras casadas | deslocamento mediano | 95% das palavras até | maior | linhas iguais | pixels diferentes |",
           "|---|---|---|---|---|---|---|"]
    diferencas = []
    tot_pal, tot_cas, tot_lin, tot_iguais, todos_desl = 0, 0, 0, 0, []
    for i in range(min(len(a), len(b))):
        pa, pb = a[i], b[i]
        areas = areas_pag[i + 1]
        wa, wb = _palavras(pa, areas), _palavras(pb, areas)
        livres = defaultdict(list)
        for w in wb:
            livres[w[0]].append(w)
        desl = []
        for t, x, y in wa:
            cands = livres.get(t)
            if not cands:
                continue
            melhor = min(cands, key=lambda c: abs(c[1] - x) + abs(c[2] - y))
            cands.remove(melhor)
            desl.append(((melhor[1] - x) ** 2 + (melhor[2] - y) ** 2) ** 0.5)
        la, lb = _linhas(pa, areas), _linhas(pb, areas)
        # sem espaços: o extrator nem sempre devolve o caractere de espaço (ex.: depois de ™),
        # mas a posição dos glifos é a mesma
        textos_b = defaultdict(list)
        for t, r in lb:
            textos_b["".join(t.split())].append(r)
        iguais = 0
        for t, r in la:
            k = "".join(t.split())
            if textos_b.get(k):
                textos_b[k].pop()
                iguais += 1
            else:
                diferencas.append((i + 1, t))

        # imagens: sobreposição e lado a lado
        ga, gb = _cinza(pa, 1.5), _cinza(pb, 1.5)
        h, w = min(ga.shape[0], gb.shape[0]), min(ga.shape[1], gb.shape[1])
        ga, gb = ga[:h, :w], gb[:h, :w]
        mascara = np.ones((h, w), bool)
        for x0, y0, x1, y1 in areas:
            mascara[int(y0 * 1.5):int(y1 * 1.5) + 1, int(x0 * 1.5):int(x1 * 1.5) + 1] = False
        dif = (np.abs(ga.astype(int) - gb.astype(int)) > 64) & mascara
        pct = 100.0 * dif.sum() / mascara.sum()
        sob = np.stack([gb, ga, ga], axis=-1)
        fitz.Pixmap(fitz.csRGB, w, h, sob.tobytes(), False).save(str(pasta / f"sobreposicao-p{i + 1}.png"))
        lado = np.concatenate([ga, np.full((h, 12), 255, np.uint8), gb], axis=1)
        fitz.Pixmap(fitz.csGRAY, lado.shape[1], h, lado.tobytes(), False).save(str(pasta / f"lado-a-lado-p{i + 1}.png"))

        med = statistics.median(desl) if desl else 0
        p95 = sorted(desl)[int(0.95 * (len(desl) - 1))] if desl else 0
        rel.append(f"| {i + 1} | {len(desl)}/{len(wa)} | {med:.2f} bp | {p95:.2f} bp | {max(desl or [0]):.1f} bp | "
                   f"{iguais}/{len(la)} | {pct:.2f}% |")
        tot_pal += len(wa); tot_cas += len(desl); tot_lin += len(la); tot_iguais += iguais
        todos_desl += desl

    med = statistics.median(todos_desl) if todos_desl else 0
    p95 = sorted(todos_desl)[int(0.95 * (len(todos_desl) - 1))] if todos_desl else 0
    rel += ["", f"**Total:** {tot_cas}/{tot_pal} palavras casadas · deslocamento mediano {med:.2f} bp · "
            f"95% até {p95:.2f} bp · {tot_iguais}/{tot_lin} linhas iguais", ""]
    if diferencas:
        rel += ["## Linhas do original que quebraram diferente no gerado", ""]
        rel += [f"- p{p}: `{t}`" for p, t in diferencas]
        rel.append("")
    rel += ["## Imagens", "",
            "`sobreposicao-pN.png`: preto = igual nos dois; **vermelho = só no original**; "
            "**azul = só no gerado**. `lado-a-lado-pN.png`: original à esquerda, gerado à direita.", ""]
    (pasta / "relatorio.md").write_text("\n".join(rel), encoding="utf-8")
    return (f"        palavras: {tot_cas}/{tot_pal} casadas, deslocamento mediano {med:.2f} bp, 95% até {p95:.2f} bp\n"
            f"        linhas iguais ao original: {tot_iguais}/{tot_lin}\n"
            f"        relatório: {pasta / 'relatorio.md'}")


if __name__ == "__main__":
    print(comparar(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
