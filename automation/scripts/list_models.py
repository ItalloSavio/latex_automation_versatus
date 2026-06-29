#!/usr/bin/env python3
"""
list_models.py — Lista os modelos reais disponíveis para a sua API Key.

Uso:
    python automation/scripts/list_models.py

Saída: nome do modelo, métodos suportados e suporte a visão.
Requisito: GEMINI_API_KEY configurado no ambiente.
"""

import os
import sys

def main():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("[ERRO] GEMINI_API_KEY não encontrada no ambiente.", file=sys.stderr)
        print("       Configure com:  set GEMINI_API_KEY=sua_chave  (Windows)", file=sys.stderr)
        sys.exit(1)

    try:
        from google import genai
    except ImportError:
        print("[ERRO] SDK não instalado. Execute: pip install google-genai", file=sys.stderr)
        sys.exit(1)

    print(f"API Key: {api_key[:8]}{'*' * (len(api_key) - 8)}\n")

    # Testa as duas rotas de API para identificar qual funciona com sua chave
    for api_version in ("v1beta", "v1"):
        print(f"{'═' * 60}")
        print(f"  Rota: {api_version}")
        print(f"{'═' * 60}")

        try:
            client = genai.Client(http_options={"api_version": api_version})
            models  = list(client.models.list())
        except Exception as exc:
            print(f"  [FALHOU] {type(exc).__name__}: {exc}\n")
            continue

        if not models:
            print("  (lista vazia — nenhum modelo retornado)\n")
            continue

        print(f"  Total de modelos retornados: {len(models)}\n")
        for m in models:
            name    = getattr(m, "name", "?")
            methods = getattr(m, "supported_generation_methods", None)
            # Imprime o valor bruto exato para diagnóstico
            print(f"  modelo : {name}")
            print(f"  métodos: {methods!r}")
            print()

    print("─" * 60)
    print("Copie o 'name' exato do modelo desejado e informe ao Claude.")
    print("Modelos marcados [VISÃO] são compatíveis com análise de imagens.")


if __name__ == "__main__":
    main()
