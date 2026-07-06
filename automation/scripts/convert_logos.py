#!/usr/bin/env python3
"""
convert_logos.py — Batch-converts a brand's SVG logos into TikZ macros.

Reads brands/<brand>/brand.json, which declares (per logo variant key,
e.g. "dark"/"light"/"alt"):
    "logo_svg": { "<key>": "logos/svg/<file>.svg", ... }
    "logos":    { "<key>": "logos/<file>.tikz",     ... }

For each variant present in logo_svg, converts the SVG using svg_to_tikz.py
(pure Python, no Inkscape/GTK) and writes the result to the path declared
under "logos". The macro name is derived as Logo<Brand><Key>, e.g.
LogoVersatusDark, LogoKosenAlt — callable later as \\LogoVersatusDark{(x,y)}.

Usage:
    python convert_logos.py --brand versatus
    python convert_logos.py --brand kosen
    python convert_logos.py --all
    python convert_logos.py --brand versatus --height 4
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_HERE       = Path(__file__).resolve().parent
_AUTOMATION = _HERE.parent
_BRANDS_DIR = _AUTOMATION.parent / "brands"


def _load_svg_to_tikz():
    spec = importlib.util.spec_from_file_location("svg_to_tikz", _HERE / "svg_to_tikz.py")
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pascal(name: str) -> str:
    return "".join(w.capitalize() for w in name.replace("-", "_").split("_"))


def convert_brand(brand_name: str, height_cm: "float | None", svg2tikz) -> int:
    brand_dir  = _BRANDS_DIR / brand_name
    brand_json = brand_dir / "brand.json"

    if not brand_json.exists():
        print(f"[ERRO] brand.json nao encontrado: {brand_json}", file=sys.stderr)
        return 0

    data = json.loads(brand_json.read_text(encoding="utf-8"))

    # Height priority: CLI --height > brand.json logo_height_cm > 3.0 default
    brand_height = data.get("logo_height_cm")
    if height_cm is not None:
        effective_height = height_cm
    elif brand_height is not None:
        effective_height = float(brand_height)
    else:
        effective_height = 3.0

    logo_svg_map = data.get("logo_svg", {})
    logo_out_map = data.get("logos", {})

    if not logo_svg_map:
        print(f"  [!] Nenhuma entrada 'logo_svg' em {brand_json.name}")
        return 0

    macro_prefix = "Logo" + _pascal(brand_name)
    converted = 0

    for key, svg_rel in logo_svg_map.items():
        svg_path = brand_dir / svg_rel
        out_rel  = logo_out_map.get(key)
        if not out_rel:
            print(f"  [!] '{key}': sem entrada correspondente em 'logos' — pulando.")
            continue

        out_path   = brand_dir / out_rel
        macro_name = macro_prefix + _pascal(key)

        if not svg_path.exists():
            print(f"  [SKIP] {key}: {svg_path.relative_to(brand_dir)} nao encontrado")
            continue

        print(f"  Convertendo {svg_path.name} -> {out_path.name}  (\\{macro_name}, h={effective_height}cm)...")
        try:
            macro_code = svg2tikz.convert(svg_path, macro_name, effective_height)
        except Exception as exc:
            print(f"    [ERRO] {exc}")
            continue

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(macro_code, encoding="utf-8")
        print(f"    [OK] -> {out_path.relative_to(brand_dir.parent)}")
        converted += 1

    return converted


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="convert_logos.py",
        description="Converte SVG logos para TikZ macros (sem Inkscape/GTK)."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--brand", metavar="NOME", help="Nome da brand (ex: versatus)")
    group.add_argument("--all",   action="store_true", help="Converte todas as brands")
    parser.add_argument("--height", type=float, default=None, help="Altura alvo em cm (default: brand.json logo_height_cm ou 3.0)")
    args = parser.parse_args()

    if not _BRANDS_DIR.exists():
        print(f"[ERRO] Pasta brands/ nao encontrada: {_BRANDS_DIR}", file=sys.stderr)
        return 1

    svg2tikz = _load_svg_to_tikz()

    brands = (
        sorted(d.name for d in _BRANDS_DIR.iterdir() if d.is_dir())
        if args.all
        else [args.brand]
    )

    total = 0
    for brand in brands:
        print(f"\n[Brand: {brand}]")
        total += convert_brand(brand, args.height, svg2tikz)

    print(f"\n{total} logo(s) convertido(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
