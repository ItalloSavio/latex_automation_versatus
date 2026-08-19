#!/usr/bin/env python3
"""
run_batch.py — run several covers and keep a LIVE progress file you can watch.

A batch takes tens of minutes and used to be invisible until it finished. This writes
`automation/output/replicated/_run_status.md` after every cover (and while one is running),
so you can keep that file open in the editor and see where it is.

Usage — group covers by how they should run:

    python automation/tools/run_batch.py plain=3,9,10 vlm=1,2,6 refresh=5,7

    plain    deterministic only
    vlm      VLM pass reusing the cached edits (no API spend)
    refresh  VLM pass calling Gemini again (COSTS API)

⚠️ capa1 must never run `plain` — a deterministic run overwrites its cached manual
deliverable (measured: 0.796 → 0.603). Put it in `vlm`.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "automation" / "scripts"
STATUS = ROOT / "automation" / "output" / "replicated" / "_run_status.md"

_FLAGS = {"plain": [], "vlm": ["--vlm"], "refresh": ["--vlm", "--vlm-refresh"]}


def _fmt(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


def _bar(done: int, total: int, width: int = 24) -> str:
    fill = int(width * done / total) if total else 0
    return "█" * fill + "░" * (width - fill)


def _write(rows, total, current, t0):
    done = len(rows)
    el = time.time() - t0
    eta = (el / done) * (total - done) if done else 0
    lines = [f"# Rodada — {done}/{total} capas",
             "",
             f"`{_bar(done, total)}` **{done}/{total}** · decorrido {_fmt(el)}"
             + (f" · restante ~{_fmt(eta)}" if done and done < total else ""),
             ""]
    if current:
        lines += [f"**Rodando agora:** capa{current[0]} ({current[1]}) — "
                  f"{_fmt(time.time() - current[2])}", ""]
    elif done == total:
        lines += ["**Concluída.**", ""]
    lines += ["| capa | modo | Score | SSIM | content | leitor? | tempo |",
              "|---|---|---:|---:|---:|---|---:|"]
    for r in rows:
        lines.append(f"| capa{r['n']} | {r['mode']} | {r['score']} | {r['ssim']} | "
                     f"{r['content']} | {r['reader']} | {_fmt(r['dt'])} |")
    if rows:
        got = [float(r["score"]) for r in rows if re.match(r"^[\d.]+$", str(r["score"]))]
        if got:
            lines += ["", f"Média parcial do Score: **{sum(got)/len(got):.4f}** ({len(got)} capas)"]
    STATUS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv):
    plan = []
    for arg in argv:
        if "=" not in arg:
            continue
        mode, nums = arg.split("=", 1)
        if mode not in _FLAGS:
            print(f"modo desconhecido: {mode}")
            return 2
        for x in nums.split(","):
            if x.strip():
                plan.append((int(x), mode))
    if not plan:
        print(__doc__)
        return 2

    bad = [n for n, m in plan if n == 1 and m == "plain"]
    if bad:
        print("recusado: capa1 nao pode rodar 'plain' (sobrescreve o entregavel cacheado)")
        return 2

    total, rows, t0 = len(plan), [], time.time()
    _write(rows, total, None, t0)
    print(f"status ao vivo -> {STATUS}\n")

    for n, mode in plan:
        img = ROOT / "capas_teste" / f"capa_teste{n}.png"
        if not img.exists():
            rows.append(dict(n=n, mode=mode, score="SEM IMAGEM", ssim="-", content="-",
                             reader="-", dt=0))
            _write(rows, total, None, t0)
            continue
        cur = (n, mode, time.time())
        _write(rows, total, cur, t0)
        print(f"[{len(rows)+1}/{total}] capa{n} ({mode}) …", flush=True)

        p = subprocess.run(
            [sys.executable, str(SCRIPTS / "replicate_cover.py"), str(img),
             "--max-passes", "2", *_FLAGS[mode]],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        out, dt = p.stdout + p.stderr, time.time() - cur[2]
        fin = re.search(r"Score final\s*:\s*([\d.]+).*?\n.*?SSIM / content:\s*([\d.]+)\s*/\s*([\d.]+)",
                        out, re.S)
        rd = re.search(r"leitor estrutural=([\d.]+)\s*(<=|>)\s*detectores=([\d.]+)", out)
        rows.append(dict(
            n=n, mode=mode,
            score=fin.group(1) if fin else f"FALHA rc={p.returncode}",
            ssim=fin.group(2) if fin else "-",
            content=fin.group(3) if fin else "-",
            reader=("leitor" if rd and rd.group(2) == ">" else "detectores") if rd else "-",
            dt=dt))
        _write(rows, total, None, t0)
        print(f"      {rows[-1]['score']}  ({_fmt(dt)})", flush=True)

    print(f"\nfim — {STATUS}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
