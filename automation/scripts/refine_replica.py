#!/usr/bin/env python3
"""refine_replica.py — o passe de REFINAMENTO da réplica (pipeline-ideal.md §4.7).

    python automation/scripts/refine_replica.py capas_teste/capa_teste6.png             # cache
    python automation/scripts/refine_replica.py capas_teste/capa_teste6.png --refresh   # Gemini
    python automation/scripts/refine_replica.py capa.png --work-dir DIR --analysis X.json

Roda sobre uma capa JÁ CONSTRUÍDA. Abre a imagem original ao lado do último render e pergunta
**onde o sistema decidiu errado** — não "o que melhorar". Não re-roda OCR nem leitor: trabalha
sobre o `analysis.json` pronto, e cada correção passa pelo mesmo portão de sempre.

## Por que FORA do pipeline (desenho do usuário, 14/09)

  1. o detector de resíduo de dentro do laço é cego a texto fino POR CONSTRUÇÃO — a abertura
     morfológica que separa mancha de anti-serrilhado apaga tipo miúdo. O mecanismo que
     deveria dizer "falta texto aqui" é o que não vê texto;
  2. um VLM comparando DUAS IMAGENS não tem essa cegueira;
  3. cada peça que entrou no laço criou regressão em outro lugar. Um passe separado pode errar
     sem contaminar a cópia — e o que ele entrega é auditável isoladamente.

## As três fontes de verdade, e o que cada uma pode dizer

  · ERROS CONFIRMADOS — `accept.check` + `accept.missing_content` contra a referência
    congelada. Determinísticos. São entregues ao VLM como "trate primeiro".
  · o VLM — vê o que nenhuma medida do pipeline vê: a linha que o OCR NUNCA leu, que por isso
    não está nem na referência (capa6: "east of mass. on 15th st.").
  · o PORTÃO (`edit_gate.run_gate`) — decide, por edit, com a métrica roteada pelo tipo.

## Pendências

Cada proposta vira um item `resolvido` (o portão aceitou) ou `bloqueado` (o portão mediu pior,
com o número). Bloqueados voltam ao VLM como "já tentado" E são filtrados no código por
assinatura — confiar só no prompt para não repetir é o que obrigou o dedup de `text.add` a
existir. Estado e propostas ficam em `refine_replica.json` (NÃO confundir com
`refine_edits.json`, que é do refinamento de LAYOUT do integrador).

## Rede de segurança

O resultado só é gravado se o veredito estrutural NÃO piorou e o Score não caiu além da guarda
sem o texto melhorar — a mesma regra do `_vlm_pass`, porque o Score é cego a tipo.
"""

import argparse
import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_HERE = Path(__file__).resolve().parent
_STATE = "refine_replica.json"
_ROUND_GUARD = 0.005          # igual ao _RESIDUAL_GUARD do replicate_cover — mesma razão


def _load(name, where=_HERE):
    spec = importlib.util.spec_from_file_location(name, where / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _severity(findings) -> int:
    """REVISAR pesa 2, ATENCAO 1. O refinamento não pode deixar isso subir."""
    return sum(2 if lv == "REVISAR" else 1 for lv, _ in findings)


def _signature(edit: dict) -> str:
    """Duas propostas são 'a mesma' se têm o mesmo op, o mesmo alvo e valores equivalentes —
    coordenadas numa grade de 0.5cm, números a uma casa. É o filtro que não depende de o VLM
    obedecer ao 'não repita'."""
    def norm(v):
        if isinstance(v, float):
            return round(v, 1)
        if isinstance(v, dict):
            return {k: (round(x * 2) / 2 if isinstance(x, (int, float)) else x)
                    for k, x in sorted(v.items())}
        if isinstance(v, list):
            return [norm(x) for x in v]
        return v
    keep = {k: norm(v) for k, v in sorted(edit.items()) if not k.startswith("_")}
    return json.dumps(keep, ensure_ascii=False, sort_keys=True)


def _describe(edit: dict) -> str:
    op = edit.get("op", "?")
    tgt = edit.get("id") or ""
    val = edit.get("value", edit.get("hex", edit.get("shape", "")))
    if isinstance(val, str):
        val = val.replace("\n", " / ")[:40]
    b = edit.get("bbox_cm")
    where = f" em x={b['x']:.1f} y={b['y']:.1f}" if isinstance(b, dict) and "x" in b else ""
    return f"{op} {tgt} {val!r}{where}".replace("  ", " ")


def refine(image_path, cover_dir, analysis_path=None, rounds: int = 3,
           refresh: bool = False, mock_rounds=None, dpi: int = 150, log=print) -> dict:
    image_path = Path(image_path).resolve()
    cover_dir = Path(cover_dir).resolve()
    analysis_path = Path(analysis_path) if analysis_path else cover_dir / "analysis.json"

    rc, gen, cmp_ = _load("replicate_cover"), _load("tikz_generator"), _load("visual_comparator")
    eg, vp = _load("edit_gate"), _load("vlm_proposer")
    acc = _load("accept", ROOT / "automation" / "tools")

    analysis = eg.assign_ids(json.loads(analysis_path.read_text(encoding="utf-8")))
    W, H = analysis["canvas"]["width_cm"], analysis["canvas"]["height_cm"]
    tikz, tex, pdf = cover_dir / "cover.tikz", cover_dir / "cover.tex", cover_dir / "cover.pdf"
    render = cover_dir / "render.png"

    def score_fn(a):
        gen.generate(a, tikz)
        rc._write_tex_wrapper(tex, tikz, a, W, H)
        ok, _ = rc._compile_lualatex(tex, pdf)
        if not ok or rc._render_pdf(pdf, render, dpi) is None:
            return None
        return cmp_.compare(image_path, render, analysis=a, output_dir=cover_dir,
                            ssim_threshold=0.95)

    # a referência: a copiada para a pasta de trabalho, senão a da capa PELO NOME DA IMAGEM.
    # Nunca pelos dígitos do nome da pasta de trabalho — "run2_capa19" daria "219".
    ref_p = cover_dir / "reference.json"
    if not ref_p.exists():
        ref_p = acc.reference_for(ROOT / "automation" / "output" / "replicated" / image_path.stem)
    ref = json.loads(ref_p.read_text(encoding="utf-8")) if ref_p else None

    def findings(a):
        f = acc.check(a)
        if ref:
            f += acc.reference_findings(a, ref, image_path, render)
        return f

    state_p = cover_dir / _STATE
    state = {"rounds": [], "items": []}
    if state_p.exists():
        try:
            state = json.loads(state_p.read_text(encoding="utf-8"))
        except Exception:
            pass
    cached = state.get("rounds") if not refresh else []
    # O HISTÓRICO de pendências sobrevive a um --refresh: é ele que impede o VLM novo de
    # repropor o que já foi medido pior. Só o cache de PROPOSTAS é descartado.
    history = list(state.get("items", []))
    items = []

    q0 = score_fn(analysis)
    if q0 is None:
        return {"ok": False, "error": "o estado de partida nao compila"}
    f0 = findings(analysis)
    log(f"[refino] {image_path.name}: Score {q0['score']:.4f} · veredito "
        f"{acc.verdict(f0)} · referencia {'sim' if ref else 'NAO'}")
    for lv, m in f0:
        log(f"   [{lv}] {m}")

    best, best_q, rounds_out = analysis, q0, []
    # O MELHOR ESTADO ENTRE RODADAS, escolhido nesta ordem: menos defeito estrutural, depois
    # maior Score. Comparar só o início com o fim jogava fora o melhor intermediário — medido
    # na capa19 ao vivo: a rodada 2 terminou com veredito OK e Score 0.9057, e a rodada 3
    # aceitou um `text.size` que colou "the" em "shining" (0.9022), colisão que nenhuma métrica
    # por caixa vê (a caixa de "shining" dá 0.900 nos três estados). Defeito ANTES de Score é
    # a ordem do pipeline-ideal §4.2: um defeito não é comprável com fração de ponto.
    sev0 = _severity(f0)
    kept, kept_q, kept_f, kept_rnd = analysis, q0, f0, 0

    def _consider(state, q, f, rnd_label):
        nonlocal kept, kept_q, kept_f, kept_rnd
        key_new, key_old = (_severity(f), -q["score"]), (_severity(kept_f), -kept_q["score"])
        if _severity(f) <= sev0 and key_new < key_old:
            kept, kept_q, kept_f, kept_rnd = copy.deepcopy(state), q, f, rnd_label

    for rnd in range(rounds):
        if rnd:
            # O portão renderiza cada candidato, então se o ÚLTIMO edit da rodada anterior foi
            # rejeitado o render.png em disco é o dele. Sem re-renderizar, a ausência seria
            # medida — e mostrada ao VLM — num render que foi recusado.
            best_q = score_fn(best) or best_q
            _consider(best, best_q, findings(best), rnd)
        fnow = findings(best)
        confirmed = [m for _, m in fnow]
        blocked = [it for it in history + items if it["status"] == "bloqueado"]
        tried = [f"{it['describe']} → {it['evidence']}" for it in blocked]

        if mock_rounds is not None:
            edits = mock_rounds[rnd] if rnd < len(mock_rounds) else []
            src = "mock"
        elif cached and rnd < len(cached):
            edits, src = cached[rnd], "cache"
        elif cached and not refresh:
            log(f"[refino] rodada {rnd+1}: cache esgotado — sem nova chamada (--refresh)")
            break
        else:
            log(f"[refino] rodada {rnd+1}: perguntando ao Gemini onde o sistema decidiu errado "
                f"({len(confirmed)} erro(s) confirmado(s), {len(tried)} ja tentado(s))...")
            edits, src = vp.propose_corrections(best, image_path, render,
                                                confirmed=confirmed, tried=tried), "gemini"
        rounds_out.append(edits)
        log(f"[refino] rodada {rnd+1}: {len(edits)} proposta(s) ({src})")
        if not edits:
            log("[refino] nenhuma decisao errada apontada — parando")
            break

        seen = {it["signature"] for it in blocked}
        fresh = [e for e in edits if _signature(e) not in seen]
        for e in edits:
            if _signature(e) in seen:
                log(f"   = ja bloqueado, ignorado: {_describe(e)}")
        if not fresh:
            log("[refino] todas as propostas ja foram medidas piores — parando")
            break

        # A pendência é registrada pela proposta CRUA, a mesma forma em que o filtro acima a
        # compara. O snap reescreve caixa e corpo — e não é idempotente —, então uma assinatura
        # tirada DEPOIS dele nunca casaria com a mesma proposta chegando de novo. Os dois snaps
        # devolvem uma saída por entrada, na ordem, e o portão um registro por edit: o zip é 1:1.
        snapped = eg.snap_text_adds(copy.deepcopy(fresh), image_path, best["canvas"])
        snapped = eg.snap_region_colors(snapped, image_path, best["canvas"], best.get("colors", []))
        best, best_q, glog = eg.run_gate(best, snapped, score_fn)
        best = eg.dedup_text(best)
        landed = 0
        for raw, entry in zip(fresh, glog):
            ok = entry["verdict"].startswith("✓")
            landed += ok
            items.append({"round": rnd + 1, "describe": _describe(raw),
                          "signature": _signature(raw),
                          "status": "resolvido" if ok else "bloqueado",
                          "evidence": f"{entry['verdict']} {entry['info']}".strip()})
            log(f"   {'✓' if ok else '✗'} {_describe(raw):<52} {entry['verdict']} {entry['info']}")
        if not landed:
            log("[refino] rodada sem nenhum edit aceito — parando")
            break

    # ── o estado final da última rodada também concorre ──────────────────────────────────
    final_q = score_fn(best) or best_q
    _consider(best, final_q, findings(best), rounds_out and len(rounds_out) or 0)

    # ── rede de segurança: fica o MELHOR estado visto, nunca pior que o de partida ────────
    # Por construção `kept` não tem mais defeito que o início. Resta a regra do _vlm_pass para
    # o caso de mesmo veredito: Score caindo além da guarda sem o texto melhorar não passa.
    t0, t1 = q0.get("text_match"), kept_q.get("text_match")
    text_worse = t0 is not None and t1 is not None and t1 < t0 - 1e-4
    ds = q0["score"] - kept_q["score"]
    same_verdict = _severity(kept_f) == sev0
    if kept is not analysis and same_verdict and ds > _ROUND_GUARD and (text_worse or t1 is None):
        log(f"[refino] melhor estado (rodada {kept_rnd}) descartado — Score caiu {ds:.4f} "
            f"sem o texto melhorar")
        kept, kept_q, kept_f, kept_rnd = analysis, q0, f0, 0
    reverted = kept is analysis and best is not analysis
    if kept_rnd == 0:
        log("[refino] nenhuma rodada terminou melhor que o estado de partida — entregavel "
            "mantido")
    elif best is not kept:
        log(f"[refino] fica o estado do FIM DA RODADA {kept_rnd} (as seguintes pioraram)")
    best, f1 = kept, kept_f
    final_q = score_fn(best) or kept_q                # o arquivo em disco == o estado mantido
    if kept_rnd:
        analysis_path.write_text(json.dumps(best, ensure_ascii=False, indent=2), encoding="utf-8")

    merged = {it["signature"]: it for it in history}
    merged.update({it["signature"]: it for it in items})         # esta rodada prevalece
    state_p.write_text(json.dumps({"rounds": rounds_out if (refresh or not cached) else cached,
                                   "items": list(merged.values())},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
    resolved = [m for _, m in f0 if m not in {mm for _, mm in f1}]
    log(f"[refino] fim: Score {q0['score']:.4f} -> {final_q['score']:.4f} · text_match "
        f"{t0} -> {final_q.get('text_match')} · veredito {acc.verdict(f0)} -> {acc.verdict(f1)}")
    for m in resolved:
        log(f"   erro confirmado RESOLVIDO: {m}")
    for lv, m in f1:
        log(f"   ainda [{lv}]: {m}")
    return {"ok": True, "reverted": reverted, "score": (q0["score"], final_q["score"]),
            "verdict": (acc.verdict(f0), acc.verdict(f1)), "items": items}


def main(argv=None):
    p = argparse.ArgumentParser(description="Passe de refinamento da replica (pos-build).")
    p.add_argument("image")
    p.add_argument("--work-dir", default=None,
                   help="roda numa COPIA desta pasta (o entregavel nao e tocado)")
    p.add_argument("--analysis", default=None, help="analysis.json de partida (default: o da pasta)")
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--refresh", action="store_true", help="chama o Gemini em vez do cache")
    a = p.parse_args(argv)

    img = Path(a.image).resolve()
    src = ROOT / "automation" / "output" / "replicated" / img.stem
    d = Path(a.work_dir).resolve() if a.work_dir else src
    if a.work_dir:
        d.mkdir(parents=True, exist_ok=True)
        for name in ("analysis.json", "render.png", "reference.json", _STATE):
            if (src / name).exists() and not (d / name).exists():
                shutil.copyfile(src / name, d / name)
        if a.analysis:
            shutil.copyfile(a.analysis, d / "analysis.json")
    res = refine(img, d, rounds=a.rounds, refresh=a.refresh)
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
