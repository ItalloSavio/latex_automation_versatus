"""O banco de provas do JUIZ. Rode isto ANTES de mexer no Score.

    python automation/tools/judge_bench.py            # todos os casos
    python automation/tools/judge_bench.py --verbose  # com o numero de cada metrica

Um juiz so vale se CONCORDA COM O OLHO nos casos em que o olho ja se pronunciou. Este arquivo
guarda esses casos como PARES — (pior, melhor) — com o veredito humano ja dado, e pergunta a
cada metrica candidata se ela ordena o par certo.

## Por que ele existe, e por que e obrigatorio

Em 2026-08-19 o Score foi trocado por um que ordenava MELHOR as 20 capas (82.9% de concordancia
contra 71.5%) e passava nos dois testes que existiam na epoca. Rodado nas 20, ele **apagou texto
de quatro capas**: duas perderam blocos inteiros, uma perdeu um titulo de 102pt, e uma virou um
borrao solido. Foi revertido no mesmo dia.

A licao: **concordancia de ordenacao NAO e teste de aceite.** O teste tem que incluir os casos
PATOLOGICOS — aqueles onde a metrica premia o resultado errado. Sao esses que este banco guarda.

## Os casos (todos MEDIDOS, nenhum hipotetico)

Cada par e uma situacao real em que o Score disse uma coisa e o olho disse outra. Sao o material
mais valioso do projeto para calibrar juiz, porque foram pagos com regressao:

  · capa19  o cache antigo do VLM APAGOU o "the" de um titulo de 135pt.
            Score SUBIU 0.8368 -> 0.8923. O olho: metade do titulo sumiu.
  · capa1   o OCR le o anel grafico como o digito "6" a 411pt (46% da altura da pagina).
            Remover esse erro CUSTA 0.13 de Score. O olho: obviamente tem que sair.
  · capa6   travada em 0.9531 com 4 linhas ilegiveis ('oonesony', 'ociooer 6 {003').
            Corrigidas pelo VLM para 6 linhas certas, o Score CAIU para 0.9524.

Um juiz aceitavel tem que acertar os TRES. O Score atual acerta ZERO — e e exatamente por isso
que existe um segundo verificador (`accept.py`) e que o olho humano ainda decide.

## Como acrescentar um caso

1. congele os dois analysis.json em `automation/bench/cases/` (nomes falando do defeito);
2. acrescente a entrada em `CASES` com o veredito e o PORQUE;
3. rode este arquivo — um caso novo que todo mundo ja acerta nao ensina nada; guarde os que
   separam.

⚠️ Fixtures vivem em `automation/bench/`, versionado. NUNCA aponte um caso para
`automation/output/`, que e sobrescrito a cada rodada.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = ROOT / "automation" / "bench" / "cases"
sys.path.insert(0, str(ROOT / "automation" / "scripts"))

# (nome, capa, arquivo PIOR, arquivo MELHOR, porque o olho decidiu assim)
CASES = [
    ("capa19: titulo inteiro vs metade apagada", 19,
     "capa19_sem_the.json", "capa19_com_the.json",
     "o cache do VLM apagou o 'the' de um titulo de 135pt; o Score SUBIU 0.055 por isso"),
    ("capa1: sem o '6' falso vs com ele", 1,
     "capa1_com_6.json", "capa1_sem_6.json",
     "o OCR le o anel como um digito de 411pt (46% da altura); remover custa 0.13 de Score"),
    ("capa6: texto legivel vs ilegivel", 6,
     "capa6_texto_ilegivel.json", "capa6_texto_corrigido.json",
     "4 linhas ilegiveis viraram 6 corretas e o Score CAIU 0.0007"),
]


def _load(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "automation" / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _text_match_ref(cover: int, img: Path, render_png: Path) -> "float | None":
    """O MESMO `text_match`, medido no QUADRO CONGELADO da referencia em vez das caixas da
    analise julgada.

    ⚠️ Este e o achado de 2026-09-16, e e um erro de REFERENCIAL, nao de formula: o `text_match`
    acumula o denominador do recall (`rec_d`) so sobre as caixas do proprio candidato, entao a
    caixa que ele OMITIU nunca entra na conta. **Uma regua fornecida pelo reu nao mede omissao.**
    Medido na capa19 (titulo com e sem o "the" de 135pt): a regua do reu da 0.9032 -> 0.8662
    (ERRA) e a regua fixa da 0.8049 -> 0.8662 (OK). Mesma funcao, mesmos pixels.

    Devolve None quando nao ha referencia congelada — o juiz nao chuta."""
    import numpy as np                                          # noqa: PLC0415
    from PIL import Image                                       # noqa: PLC0415
    ref_p = ROOT / "automation" / "bench" / "refs" / f"capa{cover}.json"
    if not ref_p.exists():
        return None
    ref = json.loads(ref_p.read_text(encoding="utf-8"))
    vc = _load("visual_comparator")
    o_img = Image.open(img).convert("RGB")
    O = np.asarray(o_img).astype(int)
    R = np.asarray(Image.open(render_png).convert("RGB")
                   .resize(o_img.size, Image.LANCZOS)).astype(int)
    W = ref["canvas"]["width_cm"]; H = ref["canvas"]["height_cm"]
    frame = vc._text_boxes_from_analysis(
        {"text_elements": ref["text_boxes"]}, W, H, O.shape)
    return vc.text_match(O, R, frame)


def render_and_measure(analysis: dict, cover: int, tag: str) -> dict:
    """Renderiza de verdade e devolve todas as metricas. Renderizar um json guardado NAO e
    rodar o pipeline — mas para comparar dois JUIZES sobre a MESMA analise, e exatamente o
    isolamento que se quer."""
    rc, tg, vc = _load("replicate_cover"), _load("tikz_generator"), _load("visual_comparator")
    d = ROOT / "automation" / "output" / "replicated" / f"capa_teste{cover}"
    img = ROOT / "capas_teste" / f"capa_teste{cover}.png"
    W, H = analysis["canvas"]["width_cm"], analysis["canvas"]["height_cm"]
    tikz, tex = d / f"bench_{tag}.tikz", d / f"bench_{tag}.tex"
    pdf, png = d / f"bench_{tag}.pdf", d / f"bench_{tag}.png"
    tg.generate(analysis, tikz)
    rc._write_tex_wrapper(tex, tikz, analysis, W, H)
    ok, err = rc._compile_lualatex(tex, pdf)
    if not ok:
        return {}
    if rc._render_pdf(pdf, png, 150) is None:
        return {}
    q = vc.compare(str(img), str(png), analysis=analysis, output_dir=d, ssim_threshold=0.95)
    tmr = _text_match_ref(cover, img, png)
    if tmr is not None:
        q["text_match_ref"] = tmr
    # o portao COMPLETO precisa do render e do quadro congelado, entao e medido aqui, onde os
    # dois existem — e nao dentro do lambda do juiz, que so recebe a analise.
    q["defect_free"] = defect_free(analysis, cover, img, png)
    return q


def n_text(a: dict) -> int:
    return len(a.get("text_elements") or [])


_ACC = None


def _accept():
    global _ACC
    if _ACC is None:
        import importlib.util                                   # noqa: PLC0415
        spec = importlib.util.spec_from_file_location(
            "accept", ROOT / "automation" / "tools" / "accept.py")
        _ACC = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_ACC)
    return _ACC


def defect_free(a: dict, cover: "int | None" = None,
                img: "Path | None" = None, render: "Path | None" = None) -> float:
    """O verificador estrutural como METRICA: 1.0 quando nao ha defeito, menos conforme acha.
    Nao mede semelhanca — mede se a pagina esta quebrada.

    ⚠️ Com `cover`/`img`/`render` ele roda o portao COMPLETO, incluindo a verificacao de
    AUSENCIA contra o quadro congelado. Sem eles roda so a parte que olha a analise — que e
    cega a omissao por construcao, e era todo o problema."""
    acc = _accept()
    f = acc.check(a)
    if cover is not None and img and render:
        ref_p = ROOT / "automation" / "bench" / "refs" / f"capa{cover}.json"
        if ref_p.exists():
            f += acc.reference_findings(
                a, json.loads(ref_p.read_text(encoding="utf-8")), img, render)
    hard = sum(1 for lv, _ in f if lv == "REVISAR")
    soft = sum(1 for lv, _ in f if lv == "ATENCAO")
    return max(0.0, 1.0 - 0.5 * hard - 0.15 * soft)


# metricas candidatas: nome -> funcao(quality_dict, analysis) -> float (maior = melhor)
JUDGES = {
    "score":          lambda q, a: q.get("score", 0.0),
    "ssim":           lambda q, a: q.get("ssim_global", 0.0),
    "content_match":  lambda q, a: q.get("content_match", 0.0),
    "text_match":     lambda q, a: q.get("text_match", 0.0),
    # o mesmo text_match, medido no quadro CONGELADO do original (ver _text_match_ref)
    "text_match_ref": lambda q, a: q.get("text_match_ref", 0.0),
    "sem_defeito":    lambda q, a: q.get("defect_free", 0.0),
    # o candidato: o Score de hoje com o verificador estrutural como VETO multiplicativo.
    # Multiplicar e nao somar e deliberado — um defeito nao deve ser compravel com fracao
    # de ponto, que foi exatamente como o texto se perdeu quatro vezes.
    "score_x_defeito": lambda q, a: q.get("score", 0.0) * q.get("defect_free", 0.0),
    # o candidato SERIO: o Score de hoje com o termo de texto medido no quadro fixo. Os pesos
    # sao os de hoje com `content_effective` cedendo metade do seu peso ao termo de presenca —
    # NAO calibrados, e nao devem ser calibrados com tres casos (ver o aviso sobre pesos nao
    # identificaveis no CLAUDE.md). Esta aqui para medir a DIRECAO, nao para entrar assim.
    "score_com_ref":  lambda q, a: (0.30 * q.get("ssim_global", 0.0)
                                    + 0.25 * q.get("content_effective", q.get("content_match", 0.0))
                                    + 0.20 * q.get("content_iou", 0.0)
                                    + 0.25 * q.get("text_match_ref", 0.0)),
}


def main(argv):
    verbose = "--verbose" in argv
    if not CASES_DIR.exists():
        print(f"[erro] fixtures ausentes em {CASES_DIR}")
        return 2

    results = {k: [0, 0] for k in JUDGES}   # [acertos, total]
    print(f"{'caso':<44} {'juiz':<17} {'pior':>8} {'melhor':>8}  veredito")
    for name, cover, worse_f, better_f, why in CASES:
        pw, pb = CASES_DIR / worse_f, CASES_DIR / better_f
        if not (pw.exists() and pb.exists()):
            print(f"{name:<44} (fixture ausente)")
            continue
        aw = json.loads(pw.read_text(encoding="utf-8"))
        ab = json.loads(pb.read_text(encoding="utf-8"))
        qw = render_and_measure(aw, cover, f"{cover}w")
        qb = render_and_measure(ab, cover, f"{cover}b")
        if not qw or not qb:
            print(f"{name:<44} (render falhou)")
            continue
        first = True
        for jn, fn in JUDGES.items():
            vw, vb = fn(qw, aw), fn(qb, ab)
            # EMPATE nao e erro, e cegueira: a metrica nao distingue o par. Contado a parte,
            # porque somar empate a "errou" faz uma metrica que so e MUDA parecer que esta
            # invertida — e as duas coisas pedem respostas diferentes.
            if abs(vb - vw) < 1e-9:
                verdict = "CEGA"
            elif vb > vw:
                verdict = "OK"
                results[jn][0] += 1
            else:
                verdict = "ERRA"
            results[jn][1] += 1
            if verbose or jn in ("score", "text_match_ref", "score_com_ref"):
                print(f"{(name if first else ''):<44} {jn:<17} "
                      f"{vw:>8.4f} {vb:>8.4f}  {verdict}")
                first = False
        print(f"{'':<44} porque: {why}")
        print(f"{'':<44} textos: pior={n_text(aw)}  melhor={n_text(ab)}")
        print()

    print(f"{'juiz':<20} concordancia com o olho")
    for jn, (ok, tot) in sorted(results.items(), key=lambda t: -t[1][0]):
        if tot:
            print(f"{jn:<20} {ok}/{tot}")
    worst = results.get("score", [0, 0])
    print(f"\nO Score atual acerta {worst[0]}/{worst[1]}. "
          f"Um juiz novo so entra se acertar MAIS e nao regredir as 9 capas.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
