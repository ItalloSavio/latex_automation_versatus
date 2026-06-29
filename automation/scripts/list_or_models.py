#!/usr/bin/env python3
"""
list_or_models.py — Lista modelos GRATUITOS com suporte a visão disponíveis no OpenRouter.

Uso:
    python automation/scripts/list_or_models.py

Requisito: OPENROUTER_API_KEY configurada no ambiente.
"""

import json
import os
import sys
import urllib.request


def main() -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print("[ERRO] OPENROUTER_API_KEY não encontrada.", file=sys.stderr)
        print("       Configure com:  set OPENROUTER_API_KEY=sk-or-v1-...  (Windows)", file=sys.stderr)
        sys.exit(1)

    print("Consultando OpenRouter API...\n")

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"[ERRO] Falha ao consultar API: {exc}", file=sys.stderr)
        sys.exit(1)

    models = data.get("data", [])
    print(f"Total de modelos retornados: {len(models)}\n")

    free_vision = []
    for m in models:
        pricing = m.get("pricing", {})
        is_free = (
            str(pricing.get("prompt",     "1")) == "0"
            and str(pricing.get("completion", "1")) == "0"
        )

        arch     = m.get("architecture", {})
        modality = arch.get("modality", "") or arch.get("input_modalities", "")
        has_vision = "image" in str(modality).lower()

        if is_free and has_vision:
            ctx     = m.get("context_length", "?")
            max_out = m.get("top_provider", {}).get("max_completion_tokens", "?")
            free_vision.append({
                "id":      m["id"],
                "name":    m.get("name", m["id"]),
                "ctx":     ctx,
                "max_out": max_out,
            })

    if not free_vision:
        print("Nenhum modelo gratuito com visão encontrado.")
        print("Verifique em: https://openrouter.ai/models (filtrar por Free + Vision)")
        return

    print(f"{'─' * 75}")
    print(f"{'MODELOS GRATUITOS COM VISÃO':^75}")
    print(f"{'─' * 75}")
    print(f"  {'ID do modelo':<52}  {'Ctx':>7}  {'Max out':>7}")
    print(f"{'─' * 75}")
    for m in sorted(free_vision, key=lambda x: x["id"]):
        ctx     = f"{m['ctx']:,}" if isinstance(m['ctx'], int) else str(m['ctx'])
        max_out = f"{m['max_out']:,}" if isinstance(m['max_out'], int) else str(m['max_out'])
        print(f"  {m['id']:<52}  {ctx:>7}  {max_out:>7}")
    print(f"{'─' * 75}")
    print(f"\nTotal: {len(free_vision)} modelo(s) gratuito(s) com visão.")
    print("\nPara usar um modelo específico:")
    print("  set OPENROUTER_MODEL=<id do modelo acima>  (Windows)")
    print("  export OPENROUTER_MODEL=<id do modelo acima>  (Linux/macOS)")


if __name__ == "__main__":
    main()
