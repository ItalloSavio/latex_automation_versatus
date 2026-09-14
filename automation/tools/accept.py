"""Esta replica saiu ENTREGAVEL? O veredito que o Score nao consegue dar.

    python automation/tools/accept.py              # todas as capas em output/replicated
    python automation/tools/accept.py 8 19         # so estas
    python automation/tools/accept.py --json       # saida para script

O Score responde "quanto isto se parece com o original". Ele NAO responde "isto esta quebrado",
e a diferenca custou caro repetidas vezes — sempre com o numero dizendo que melhorou:

  · capa19 perdeu o `"the"` do titulo e o Score SUBIU 0.055 (apagar meio titulo de 135pt custa
    menos que desenha-lo);
  · capa8 teve `'the velvet'` apagado e ficou um buraco, com +0.003;
  · capa1 mantem um `"6"` de 411pt que e o anel lido como digito, porque remover custa 0.13;
  · capa8 ganhou uma barra preta atras das legendas sem o Score reagir.

Nenhum desses aparece numa comparacao de pixels ponderada por area. Todos aparecem olhando a
ANALISE com as perguntas certas, e e isso que este arquivo faz. Ele nao mede semelhanca —
mede se a pagina tem defeito estrutural.

Veredito por capa: OK, ATENCAO (defeito provavel) ou REVISAR (defeito quase certo).
Sai com codigo 1 se alguma capa ficou em REVISAR, para servir de portao em script.
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "automation" / "output" / "replicated"

# Um em maior que esta fracao da altura da pagina quase nunca e tipografia. capa1 le o anel
# como um "6" de 411pt = 14.5cm de em numa pagina de 29.55cm (49%); os titulos legitimos mais
# generosos do conjunto ficam em 135pt (4.8cm, 16%). 25% separa os dois com folga.
_EM_MAX_FRAC = 0.25
# Tinta a mais que esta distancia de QUALQUER cor da paleta e cor inventada. O estimador de cor
# media o centroide do cluster de tinta (borda anti-serrilhada inclusa) e devolvia cinza onde o
# design e branco; 60 pega isso sem acusar o branco puro legitimo, que fica a ~75 em capas cuja
# paleta nao tem branco.
_COLOR_MAX_DIST = 90.0
# Polignos tracados MINUSCULOS em fileira sao letras que o OCR nao leu, desenhadas como manchas.
_GLYPH_MAX_CM2 = 2.0
_GLYPH_MIN_RUN = 4          # menos que isto pode ser arte legitima (pontos, marcas)
_PIECES_WARN = 550          # _MAX_PIECES do leitor e 600; perto disso a capa estilhacou


def _rgb(h):
    h = (h or "#000000").lstrip("#")
    try:
        return [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    except Exception:
        return [0, 0, 0]


def _overlap(a, b):
    ow = max(0.0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    oh = max(0.0, min(a["y"] + a.get("h", .3), b["y"] + b.get("h", .3)) - max(a["y"], b["y"]))
    return ow * oh


def check(analysis: dict) -> list:
    """Devolve [(nivel, mensagem)] — nivel 'REVISAR' ou 'ATENCAO'."""
    W = analysis["canvas"]["width_cm"]
    H = analysis["canvas"]["height_cm"]
    els = [e for e in (analysis.get("text_elements") or []) if (e.get("bbox_cm") or {}).get("w")]
    regs = analysis.get("regions") or []
    pal = [_rgb(c.get("hex")) for c in (analysis.get("colors") or [])]
    out = []

    # 1 — tipo vazando da pagina
    for e in els:
        b = e["bbox_cm"]
        if b["x"] + b["w"] > W + 0.05 or b["y"] + b.get("h", .3) > H + 0.05 \
           or b["x"] < -0.05 or b["y"] < -0.05:
            over = max(b["x"] + b["w"] - W, b["y"] + b.get("h", .3) - H, -b["x"], -b["y"])
            out.append(("REVISAR", f"texto {e.get('text','')[:22]!r} sai {over:.2f}cm da pagina"))

    # 2 — blocos de texto sobrepostos
    for i in range(len(els)):
        for j in range(i + 1, len(els)):
            a, b = els[i]["bbox_cm"], els[j]["bbox_cm"]
            ov = _overlap(a, b)
            if ov <= 0:
                continue
            small = min(a["w"] * a.get("h", .3), b["w"] * b.get("h", .3)) or 1.0
            if ov / small > 0.30:
                out.append(("ATENCAO",
                            f"{els[i].get('text','')[:16]!r} e {els[j].get('text','')[:16]!r} "
                            f"se sobrepoem em {100*ov/small:.0f}%"))

    # 3 — tipo grande demais para ser tipo
    for e in els:
        em_cm = (e.get("font_size_pt") or 0) / 28.35
        if em_cm > _EM_MAX_FRAC * H:
            out.append(("REVISAR",
                        f"texto {e.get('text','')[:22]!r} a {e.get('font_size_pt'):.0f}pt ocupa "
                        f"{100*em_cm/H:.0f}% da altura — provavel grafico lido como texto"))

    # 4 — cor de tinta que nao existe no desenho
    if pal:
        for e in els:
            c = _rgb(e.get("color_hex"))
            d = min(math.dist(c, p) for p in pal)
            if d > _COLOR_MAX_DIST:
                out.append(("ATENCAO",
                            f"texto {e.get('text','')[:22]!r} usa {e.get('color_hex')}, "
                            f"a {d:.0f} de qualquer cor medida"))

    # 5 — letras desenhadas como manchas: poligonos minusculos alinhados em fileira
    tiny = [r for r in regs
            if r.get("points_cm")
            and (r.get("bbox_cm") or {}).get("w", 0) * (r.get("bbox_cm") or {}).get("h", 0)
            <= _GLYPH_MAX_CM2]
    rows: dict = {}
    for r in tiny:
        rows.setdefault(round(r["bbox_cm"]["y"], 1), []).append(r)
    for y, group in rows.items():
        if len(group) >= _GLYPH_MIN_RUN:
            out.append(("ATENCAO",
                        f"{len(group)} poligonos minusculos alinhados em y={y}cm — "
                        f"provavel palavra que o OCR nao leu, desenhada como mancha"))

    # 6 — a capa estilhacou
    if len(regs) >= _PIECES_WARN:
        out.append(("ATENCAO", f"{len(regs)} pecas — perto do teto do leitor (600)"))

    # 7 — nada de texto numa capa que tem zonas de texto medidas
    if not els and (analysis.get("text_zones") or []):
        out.append(("REVISAR", "nenhum texto no entregavel, mas a analise mediu zonas de texto"))

    return out


def verdict(findings) -> str:
    if any(lv == "REVISAR" for lv, _ in findings):
        return "REVISAR"
    return "ATENCAO" if findings else "OK"


def main(argv):
    as_json = "--json" in argv
    argv = [a for a in argv if not a.startswith("--")]
    nums = argv or sorted(
        "".join(c for c in p.name if c.isdigit())
        for p in OUT.glob("capa_teste*") if p.is_dir())

    report, bad = {}, 0
    for n in nums:
        aj = OUT / f"capa_teste{n}" / "analysis.json"
        if not aj.exists():
            continue
        f = check(json.loads(aj.read_text(encoding="utf-8")))
        v = verdict(f)
        report[f"capa{n}"] = {"veredito": v, "achados": [m for _, m in f]}
        bad += v == "REVISAR"

    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{'capa':>7}  {'veredito':<9} achados")
        for k, v in report.items():
            first = v["achados"][0] if v["achados"] else "—"
            print(f"{k:>7}  {v['veredito']:<9} {first}")
            for extra in v["achados"][1:]:
                print(f"{'':>7}  {'':<9} {extra}")
        ok = sum(1 for v in report.values() if v["veredito"] == "OK")
        print(f"\n{ok}/{len(report)} sem defeito estrutural detectado.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
