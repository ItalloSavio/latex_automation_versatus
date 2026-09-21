"""Congela o QUADRO DE REFERENCIA de uma capa: o que o OCR leu no ORIGINAL, antes de qualquer
portao ter a chance de apagar alguma coisa.

    python automation/tools/make_reference.py 1 6 19

## Por que isto existe — a regua nao pode vir do reu

O `text_match` mede a tinta DENTRO das caixas de texto, e as caixas saiam da **propria analise
julgada**. O denominador do recall (`rec_d`) so acumula sobre as caixas do candidato, entao a
caixa que o candidato OMITIU nunca e cobrada: apagar um elemento e literalmente de graca.

Medido no banco (2026-09-16), capa19 — o titulo com e sem o `"the"` de 135pt:

    regua DO REU (cada um nas suas caixas) : 0.9032 -> 0.8662   ERRA
    regua FIXA   (ambos no mesmo quadro)   : 0.8049 -> 0.8662   OK

A mesma metrica, sem uma linha de mudanca na formula, passa a acertar assim que os dois lados
sao medidos no MESMO quadro. Era um erro de referencial, nao de formula.

## O que este arquivo congela, e por que e do OCR bruto

A saida de `cover_assembler._run_ocr` — o estagio 1, ANTES do `_select_text`, do VLM e de
qualquer edicao. E a unica leitura do original que nenhum candidato influenciou.

⚠️ O desenho escrito em `pipeline-ideal.md` §4.3 era comparar STRINGS ("toda linha que o OCR
leu com confianca alta tem correspondente no entregavel?"). Medido, isso REPROVA a capa1: o
anel lido como um `"6"` de 411pt e uma linha de confianca alta, e remove-lo — que e o certo —
seria acusado como ausencia. Medir TINTA no quadro fixo nao tem esse problema, porque ali o
original de fato tem tinta (o anel) e a pergunta passa a ser "voce poe tinta parecida aqui?",
que o anel desenhado como anel responde tao bem quanto o `"6"` respondia.

Por isso o que se congela e a GEOMETRIA (as caixas), e a string vai junto so como legenda
humana — nada mede a string.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFS = ROOT / "automation" / "bench" / "refs"
sys.path.insert(0, str(ROOT / "automation" / "scripts"))


def _load(name):
    import importlib.util                                       # noqa: PLC0415
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "automation" / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build(cover: int) -> dict:
    """Roda o OCR do estagio 1 no original e devolve o quadro de referencia."""
    ca = _load("cover_assembler")
    img = ROOT / "capas_teste" / f"capa_teste{cover}.png"
    aj = ROOT / "automation" / "output" / "replicated" / f"capa_teste{cover}" / "analysis.json"
    canvas = json.loads(aj.read_text(encoding="utf-8"))["canvas"]
    W, H = canvas["width_cm"], canvas["height_cm"]
    els = ca._run_ocr(img, W, H)
    return {
        "source_image": img.name,
        "canvas": {"width_cm": W, "height_cm": H},
        "note": "OCR do estagio 1, antes de qualquer portao. A GEOMETRIA e o que mede; "
                "a string vai junto so como legenda humana.",
        "text_boxes": [
            {"text": e.get("text", ""),
             "confidence": round(float(e.get("confidence") or 0.0), 3),
             "bbox_cm": e.get("bbox_cm")}
            for e in els if (e.get("bbox_cm") or {}).get("w")
        ],
    }


def main(argv):
    nums = [int(a) for a in argv if a.isdigit()]
    if not nums:
        print(__doc__.strip().splitlines()[2])
        return 2
    REFS.mkdir(parents=True, exist_ok=True)
    for i, n in enumerate(nums, 1):
        print(f"[{i}/{len(nums)}] capa{n}: rodando o OCR no original...", flush=True)
        ref = build(n)
        p = REFS / f"capa{n}.json"
        p.write_text(json.dumps(ref, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"          {len(ref['text_boxes'])} caixas -> {p.relative_to(ROOT)}", flush=True)
        for b in ref["text_boxes"]:
            print(f"            {b['text']!r:<26} conf={b['confidence']:.2f}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
