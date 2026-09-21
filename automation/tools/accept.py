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

⚠️ ATE 2026-09-16 ELE NAO VIA AUSENCIA. Olhando so a analise final, nao havia como saber o que
sumiu: a capa19 que perdeu o `"the"` era aprovada com `OK`. O que faltava nao era uma regra, era
uma REFERENCIA — e o pipeline tinha essa informacao e a jogava fora. Ver `missing_content()` e
`automation/tools/make_reference.py`.

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

# ── ausencia de conteudo: medida contra o QUADRO CONGELADO da referencia ──────────────────
# Piso de confianca da leitura que vira cobranca. E o mesmo `_MIN_CONFIDENCE` do `ocr_extractor`
# de proposito: abaixo dele a propria leitura e duvidosa, e cobrar a ausencia de algo que talvez
# nem exista ali produz alarme falso. Medido — as tres leituras ilegiveis da capa6 ('oonesony'
# 0.26, 'ociooer 6 {003' 0.37, 'huybock mochine' 0.27) tem recall 0.000 nos DOIS lados do par do
# banco: sem este piso, as duas versoes seriam acusadas igualmente e o teste nao separaria nada.
_REF_MIN_CONF = 0.50
# Abaixo disto o entregavel nao poe tinta parecida onde o original tem. Escolhido com os dois
# lados na mao, como o `_EM_MAX_FRAC`: nos 6 renders do banco o menor recall LEGITIMO medido e
# 0.504, e o unico caso de ausencia real e o `"the"` da capa19 a 0.095 — 0.35 cai no meio de um
# vao de ~5x para cada lado.
_REF_MISS_RECALL = 0.35
# Abaixo disto nao e "malposto", e "nao esta la". Separa o `"the"` da capa19 (0.095 — o titulo
# que foi ENTREGUE pela metade) do titulo da capa1 (0.246 — desenhado, so que grande demais e
# deslocado): dois defeitos diferentes, severidades diferentes.
_REF_GONE_RECALL = 0.15
# Margem em volta de uma marca DECLARADA. Ali o sistema deliberadamente nao desenha (o North Star
# manda identificar, nao reconstruir), entao cobrar a tinta do original seria cobrar a regra do
# projeto. A caixa do placeholder e MENOR que a marca do original — na capa1 cobre so 38% da
# leitura 'versatus' e 11% de 'HPC' — por isso o teste e o CENTRO dentro da zona dilatada, nunca
# contencao por area, que deixaria as duas passarem.
_LOGO_MARGIN_CM = 1.0
_REF_INK_DIST = 55          # mesma familia de limiar do `text_match` (visual_comparator)
_REF_DILATE_PX = 3          # mesma tolerancia de desalinhamento do `text_match`

# ── palavras coladas: o espaço que o original tem entre duas palavras sumiu no render ─────
# Coluna VAZIA = coluna de cor uniforme na faixa da linha (máx desvio-padrão por canal abaixo
# disto). Um espaço entre palavras é uma coluna só de fundo, seja o fundo preto, amarelo ou
# creme — por isso o teste é UNIFORMIDADE, não distância a uma cor de fundo: na capa19 o
# espaço entre "the" e "shining" cai exatamente na fronteira preto/amarelo.
_GAP_STD_MAX = 20.0
_GAP_WINDOW_CM = 0.30       # meia-largura da janela em volta da fronteira entre as caixas
_GAP_MIN_ORIG_PX = 3        # o original precisa ter um espaço de verdade ali
_GAP_MAX_RENDER_PX = 2      # abaixo disto o render não tem espaço nenhum: colou
# Só para tipo de DISPLAY, e o limite veio da medição (17/09), com os dois lados na mão: no
# título da capa19 a linha tem ~100px na imagem-fonte e o espaço entre palavras 6px — o
# detector acusa o "theshining" do refino (6px → 0px) e passa o entregue (13px). No cabeçalho
# da capa2 a linha tem ~7px e o espaço 1–3px, que é ruído: ali ele PERDEU uma colisão visível
# e na capa1 (13px) acusou espaçamento apertado que não é colisão. Abaixo disto a medição
# não existe — é o teto de resolução do pos-mvp §D2, e o juiz não chuta.
_GAP_MIN_LINE_PX = 16


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


def reference_for(cover_dir: Path):
    """O quadro congelado desta capa, se existir.

    Duas casas, nesta ordem: o `reference.json` ao lado do entregavel — que e o que o pipeline
    escreve para uma imagem QUALQUER, inclusive fora do corpus — e, so para as capas numeradas,
    `automation/bench/refs/capaN.json`. As do corpus moram versionadas porque
    `automation/output/` nao e versionado e e sobrescrito a cada rodada; as nove entregues
    foram analisadas antes desta peca existir e por isso nao tem o arquivo local.
    """
    local = cover_dir / "reference.json"
    if local.exists():
        return local
    n = "".join(c for c in cover_dir.name if c.isdigit())
    if not n:
        return None
    frozen = ROOT / "automation" / "bench" / "refs" / f"capa{n}.json"
    return frozen if frozen.exists() else None


def _mark_zones(analysis: dict) -> list:
    """Onde o sistema DECLAROU uma marca e por isso nao desenha a tinta do original."""
    zones = [lg["bbox_cm"] for lg in (analysis.get("logos") or []) if lg.get("bbox_cm")]
    zones += [e["bbox_cm"] for e in (analysis.get("text_elements") or [])
              if "(Logo)" in (e.get("text") or "") and e.get("bbox_cm")]
    return zones


def missing_content(analysis: dict, reference: dict, image_path, render_path) -> list:
    """O original tem tinta AQUI — o entregavel poe tinta parecida aqui?

    Esta e a pergunta que o Score nao faz, e a razao e um erro de REFERENCIAL, nao de formula:
    o `text_match` acumula o denominador do recall (`rec_d`) so sobre as caixas da PROPRIA
    analise julgada, entao a caixa que o candidato OMITIU nunca entra na conta. **Uma regua
    fornecida pelo reu nao mede omissao.** Medido na capa19, o titulo com e sem o "the" de 135pt:

        regua DO REU (cada um nas suas caixas) : 0.9032 -> 0.8662   ERRA
        regua FIXA   (ambos no mesmo quadro)   : 0.8049 -> 0.8662   OK

    Mesma funcao, mesmos pixels, ordem invertida — so mudou quem segura a regua.

    Aqui a ideia vira acusacao NOMINAL: para cada caixa do quadro congelado, quanto da tinta do
    ORIGINAL tem tinta do render por perto. Nao se compara STRING com string — o desenho de
    `pipeline-ideal.md` §4.3 era comparar as leituras, e medido isso REPROVA a capa1: o anel
    lido como um `"6"` de 411pt e uma leitura de confianca ALTA que o certo e justamente
    remover. Perguntando por TINTA, o anel desenhado como anel responde tao bem quanto o `"6"`
    respondia, e o caso deixa de ser um falso alarme.

    Devolve [] quando falta referencia, render ou as libs — o juiz nao chuta.
    """
    try:
        import numpy as np                                        # noqa: PLC0415
        from PIL import Image                                     # noqa: PLC0415
        from scipy.ndimage import binary_dilation                 # noqa: PLC0415
    except Exception:
        return []
    boxes = (reference or {}).get("text_boxes") or []
    if not boxes or not Path(image_path).exists() or not Path(render_path).exists():
        return []

    o_img = Image.open(image_path).convert("RGB")
    O = np.asarray(o_img).astype(int)
    R = np.asarray(Image.open(render_path).convert("RGB")
                   .resize(o_img.size, Image.LANCZOS)).astype(int)
    h_px, w_px = O.shape[:2]
    W = reference["canvas"]["width_cm"]
    H = reference["canvas"]["height_cm"]
    zones = _mark_zones(analysis)

    def _bg(roi):
        q = (roi // 16).reshape(-1, 3)
        vals, counts = np.unique(q, axis=0, return_counts=True)
        return vals[counts.argmax()] * 16 + 8

    out = []
    for t in boxes:
        txt = (t.get("text") or "").strip()
        b = t.get("bbox_cm") or {}
        if not txt or not b.get("w"):
            continue      # o split bicolor pode devolver uma metade sem leitura nenhuma
        if float(t.get("confidence") or 0.0) < _REF_MIN_CONF:
            continue
        cx, cy = b["x"] + b["w"] / 2.0, b["y"] + b["h"] / 2.0
        if any(z["x"] - _LOGO_MARGIN_CM <= cx <= z["x"] + z["w"] + _LOGO_MARGIN_CM
               and z["y"] - _LOGO_MARGIN_CM <= cy <= z["y"] + z["h"] + _LOGO_MARGIN_CM
               for z in zones):
            continue      # marca declarada: nao desenhar ali e a regra, nao o defeito

        x0 = max(0, int(b["x"] / W * w_px) - 3)
        x1 = min(w_px, int((b["x"] + b["w"]) / W * w_px) + 3)
        y0 = max(0, int(h_px - (b["y"] + b["h"]) / H * h_px) - 3)
        y1 = min(h_px, int(h_px - b["y"] / H * h_px) + 3)
        if x1 <= x0 or y1 <= y0:
            continue
        ob, rb = O[y0:y1, x0:x1], R[y0:y1, x0:x1]
        bg = _bg(O[y0:y1, x0:x1])
        ink_o = np.sqrt(((ob - bg) ** 2).sum(2)) > _REF_INK_DIST
        if not ink_o.sum():
            continue
        ink_r = np.sqrt(((rb - bg) ** 2).sum(2)) > _REF_INK_DIST
        rec = float((ink_o & binary_dilation(ink_r, iterations=_REF_DILATE_PX)).sum()
                    / ink_o.sum())
        if rec >= _REF_MISS_RECALL:
            continue
        pct = 100.0 * int(ink_o.sum()) / (h_px * w_px)
        if rec < _REF_GONE_RECALL:
            out.append(("REVISAR",
                        f"o original le {txt[:22]!r} aqui ({pct:.2f}% da pagina) e o entregavel "
                        f"nao poe quase nada — recall {rec:.2f}"))
        else:
            out.append(("ATENCAO",
                        f"{txt[:22]!r} esta desenhado fora de lugar ou fora de escala — "
                        f"recall {rec:.2f} contra a referencia"))
    return out


def word_collisions(analysis: dict, reference: dict, image_path, render_path) -> list:
    """O original tem um ESPAÇO entre estas duas palavras — o render ainda tem?

    A classe apareceu duas vezes no mesmo dia (17/09), por caminhos independentes: o passe de
    refinamento aceitou um `text.size` que colou "the" em "shining" na capa19, e um rebuild
    colou "SÉRIE /" em "Versatus HPC…" na capa2. Nas duas, cada linha melhorou NA PRÓPRIA
    caixa — é o ponto cego de julgar tipo caixa a caixa — e nenhuma métrica viu: a caixa de
    "shining" dá F1 0.900 com e sem a colisão, porque o "e" encosta na fronteira da janela.

    Os PARES vêm da referência, não do candidato: é o original que diz onde há duas palavras
    lado a lado. O espaço é medido em pixels nos dois lados, no mesmo quadro.

    Devolve [] sem referência, render ou libs; e não opina sobre tipo miúdo demais para ter
    um espaço mensurável (ver `_GAP_MIN_LINE_PX`).
    """
    try:
        import numpy as np                                        # noqa: PLC0415
        from PIL import Image                                     # noqa: PLC0415
    except Exception:
        return []
    boxes = [t for t in ((reference or {}).get("text_boxes") or [])
             if (t.get("text") or "").strip() and (t.get("bbox_cm") or {}).get("w")
             and float(t.get("confidence") or 0.0) >= _REF_MIN_CONF]
    if len(boxes) < 2 or not Path(image_path).exists() or not Path(render_path).exists():
        return []
    o_img = Image.open(image_path).convert("RGB")
    O = np.asarray(o_img).astype(float)
    R = np.asarray(Image.open(render_path).convert("RGB")
                   .resize(o_img.size, Image.LANCZOS)).astype(float)
    h_px, w_px = O.shape[:2]
    W = reference["canvas"]["width_cm"]
    H = reference["canvas"]["height_cm"]
    zones = _mark_zones(analysis)

    def in_mark(b):
        cx, cy = b["x"] + b["w"] / 2.0, b["y"] + b["h"] / 2.0
        return any(z["x"] - _LOGO_MARGIN_CM <= cx <= z["x"] + z["w"] + _LOGO_MARGIN_CM
                   and z["y"] - _LOGO_MARGIN_CM <= cy <= z["y"] + z["h"] + _LOGO_MARGIN_CM
                   for z in zones)

    def longest_empty(arr, r0, r1, c0, c1):
        empty = arr[r0:r1, c0:c1].std(axis=0).max(axis=1) < _GAP_STD_MAX
        best = cur = 0
        for v in empty:
            cur = cur + 1 if v else 0
            best = max(best, cur)
        return best

    out = []
    for i, ta in enumerate(boxes):
        for tb in boxes[i + 1:]:
            a, b = ta["bbox_cm"], tb["bbox_cm"]
            if a["x"] > b["x"]:
                ta, tb, a, b = tb, ta, b, a
            if in_mark(a) or in_mark(b):
                continue
            lo, hi = max(a["y"], b["y"]), min(a["y"] + a["h"], b["y"] + b["h"])
            if hi - lo < 0.5 * min(a["h"], b["h"]):
                continue                                  # não é a mesma linha
            if not -0.5 <= b["x"] - (a["x"] + a["w"]) <= 1.0:
                continue                                  # não são vizinhas
            if (hi - lo) / H * h_px < _GAP_MIN_LINE_PX:
                continue                                  # abaixo do teto de resolução
            pad = 0.1 * (hi - lo)
            r0, r1 = int((H - (hi - pad)) / H * h_px), int((H - (lo + pad)) / H * h_px)
            edge = (a["x"] + a["w"] + b["x"]) / 2.0
            c0 = max(0, int((edge - _GAP_WINDOW_CM) / W * w_px))
            c1 = min(w_px, int((edge + _GAP_WINDOW_CM) / W * w_px))
            if r1 <= r0 or c1 <= c0:
                continue
            g_o = longest_empty(O, r0, r1, c0, c1)
            g_r = longest_empty(R, r0, r1, c0, c1)
            if g_o >= _GAP_MIN_ORIG_PX and g_r < _GAP_MAX_RENDER_PX:
                out.append(("ATENCAO",
                            f"{ta['text'][:18]!r} e {tb['text'][:18]!r} COLARAM — o original "
                            f"tem {g_o}px de espaco entre elas, o entregavel {g_r}px"))
    return out


def reference_findings(analysis: dict, reference: dict, image_path, render_path) -> list:
    """Tudo que só se vê comparando o entregável com o ORIGINAL através da referência congelada:
    conteúdo ausente e palavras coladas. Ponto de entrada ÚNICO — o accept, o cover_pipeline,
    o refine_replica e o judge_bench chamam isto, para as regras não divergirem entre cópias."""
    return (missing_content(analysis, reference, image_path, render_path)
            + word_collisions(analysis, reference, image_path, render_path))


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

    report, bad, sem_ref = {}, 0, []
    for n in nums:
        d = OUT / f"capa_teste{n}"
        aj = d / "analysis.json"
        if not aj.exists():
            continue
        analysis = json.loads(aj.read_text(encoding="utf-8"))
        f = check(analysis)
        # a verificacao de AUSENCIA so roda com quadro congelado. Sem ele o check nao opina —
        # e isso e REPORTADO, nunca convertido em achado: transformar "nao medi" em "achei algo"
        # e a forma mais rapida de um portao virar ruido.
        ref_p = reference_for(d)
        if ref_p:
            f += reference_findings(analysis, json.loads(ref_p.read_text(encoding="utf-8")),
                                    ROOT / "capas_teste" / f"capa_teste{n}.png", d / "render.png")
        else:
            sem_ref.append(f"capa{n}")
        v = verdict(f)
        report[f"capa{n}"] = {"veredito": v, "achados": [m for _, m in f],
                              "ausencia_verificada": bool(ref_p)}
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
        if sem_ref:
            print(f"⚠️  sem quadro de referencia, AUSENCIA nao verificada em: "
                  f"{', '.join(sem_ref)}  "
                  f"(python automation/tools/make_reference.py {' '.join(s[4:] for s in sem_ref)})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
