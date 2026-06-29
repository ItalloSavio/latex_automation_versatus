#!/usr/bin/env python3
"""
json_to_tikz.py — Canvas AST JSON → TikZ/LaTeX macro converter.

Validates a JSON file against canvas_schema.json, translates the element
tree into TikZ draw commands, and writes a \\RenderDynamicCover macro to
styles/versatus-dynamic-cover.tex.

CLI usage:
    python json_to_tikz.py <canvas.json> [output.tex]

API usage:
    from automation.core.json_to_tikz import convert
    convert(Path("my_cover.json"))
"""

import json
import re
import sys
from pathlib import Path

import jsonschema

# ─── Paths ────────────────────────────────────────────────────────────────────

_HERE         = Path(__file__).resolve().parent
_SCHEMA_PATH  = _HERE.parent / "schema" / "canvas_schema.json"
_PROJECT_ROOT = _HERE.parent.parent
_DEFAULT_OUT  = _PROJECT_ROOT / "styles" / "versatus-dynamic-cover.tex"

# ─── Helpers ──────────────────────────────────────────────────────────────────

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _is_hex(color: str) -> bool:
    return bool(_HEX_RE.match(color))


def _hex6(color: str) -> str:
    """Normalise #RGB / #RRGGBB → 6-digit uppercase hex string (no '#')."""
    h = color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return h.upper()


def _fmt(n: float) -> str:
    """Format a float cleanly: drop the decimal point when it's a whole number."""
    return str(int(n)) if isinstance(n, float) and n == int(n) else str(n)


def _build_hex_map(elements: list) -> dict[str, str]:
    """
    Scan all elements for hex colours and return a mapping
    { hex6_string → safe_latex_name } in encounter order.
    Handles both single 'color' fields and 'colors' arrays (PatternElement).
    """
    mapping: dict[str, str] = {}
    counter = 0

    def _register(c: str) -> None:
        nonlocal counter
        if c and _is_hex(c):
            h6 = _hex6(c)
            if h6 not in mapping:
                mapping[h6] = f"dyncolor{counter}"
                counter += 1

    for el in elements:
        _register(el.get("color", ""))
        for c in el.get("colors", []):
            _register(c)

    return mapping


def _cname(color: str, hex_map: dict[str, str]) -> str:
    """Resolve a color string to a TikZ-safe name."""
    if _is_hex(color):
        return hex_map[_hex6(color)]
    return color


# ─── Per-element TikZ emitters ────────────────────────────────────────────────

def _emit_background(el: dict, hm: dict) -> str:
    c = _cname(el["color"], hm)
    # Intentional bleed: extends 1 cm beyond A4 on all sides
    return rf"\fill[{c}] (-1, -1) rectangle (22, 31);"


def _emit_rectangle(el: dict, hm: dict) -> str:
    c = _cname(el["color"], hm)
    x1, y1 = _fmt(el["x1"]), _fmt(el["y1"])
    x2, y2 = _fmt(el["x2"]), _fmt(el["y2"])
    angle   = el.get("rotation", 0)

    if not angle:
        return rf"\fill[{c}] ({x1}, {y1}) rectangle ({x2}, {y2});"

    cx = _fmt((el["x1"] + el["x2"]) / 2)
    cy = _fmt((el["y1"] + el["y2"]) / 2)
    return rf"\fill[{c}, rotate around={{{_fmt(angle)}:({cx}, {cy})}}] ({x1}, {y1}) rectangle ({x2}, {y2});"


def _emit_circle(el: dict, hm: dict) -> str:
    c  = _cname(el["color"], hm)
    cx, cy = _fmt(el["cx"]), _fmt(el["cy"])
    r  = _fmt(el["radius"])
    # Explicit cm unit required: with y=-1cm the coordinate axes are asymmetric
    # and bare numbers would produce an ellipse instead of a circle.
    return rf"\fill[{c}] ({cx}, {cy}) circle [radius={r}cm];"


def _emit_triangle(el: dict, hm: dict) -> str:
    c = _cname(el["color"], hm)
    x1, y1 = _fmt(el["x1"]), _fmt(el["y1"])
    x2, y2 = _fmt(el["x2"]), _fmt(el["y2"])
    x3, y3 = _fmt(el["x3"]), _fmt(el["y3"])
    return rf"\fill[{c}] ({x1},{y1}) -- ({x2},{y2}) -- ({x3},{y3}) -- cycle;"


def _emit_line(el: dict, hm: dict) -> str:
    c = _cname(el["color"], hm)
    x1, y1 = _fmt(el["x1"]), _fmt(el["y1"])
    x2, y2 = _fmt(el["x2"]), _fmt(el["y2"])
    w = _fmt(el["width"])
    return rf"\draw[{c}, line width={w}pt] ({x1}, {y1}) -- ({x2}, {y2});"


def _emit_pattern(el: dict, hm: dict) -> str:
    """
    Generate a TikZ \\foreach loop for a repeating geometric pattern.
    Supports: circle_grid, rect_grid (with optional rotation and stagger).
    """
    pt      = el["pattern_type"]
    cols    = el["cols"]
    rows    = el["rows"]
    xs      = _fmt(el["x_start"])
    ys      = _fmt(el["y_start"])
    xstep   = _fmt(el["x_step"])
    ystep   = _fmt(el["y_step"])
    colors  = [_cname(c, hm) for c in el["colors"]]
    nc      = len(colors)
    rule    = el.get("color_rule", "checker")
    stagger = el.get("stagger", False)

    rule_expr = {
        "checker": f"mod(\\col+\\row,{nc})",
        "row":     f"mod(\\row,{nc})",
        "col":     f"mod(\\col,{nc})",
    }.get(rule, f"mod(\\col+\\row,{nc})")

    def color_block(template: str) -> list[str]:
        """Build \\ifnum...\\else...\\fi chain. Template uses COLOR as placeholder."""
        if nc == 1:
            return [template.replace("COLOR", colors[0])]
        out = []
        for i, c in enumerate(colors):
            line = template.replace("COLOR", c)
            if i == 0:
                out.append(f"      \\ifnum\\cidx={i} {line}")
            elif i < nc - 1:
                out.append(f"      \\else\\ifnum\\cidx={i} {line}")
            else:
                out.append(f"      \\else {line}")
        out.append("      " + "\\fi" * (nc - 1))
        return out

    body = [
        f"\\foreach \\row in {{0,...,{rows - 1}}}{{",
        f"  \\foreach \\col in {{0,...,{cols - 1}}}{{",
        f"    \\pgfmathtruncatemacro{{\\cidx}}{{{rule_expr}}}",
    ]

    if stagger:
        body.append("    \\pgfmathtruncatemacro{\\isoddr}{mod(\\row,2)}")

    if pt == "circle_grid":
        if "radius" not in el:
            raise ValueError("circle_grid pattern requires 'radius'")
        r = _fmt(el["radius"])
        if stagger:
            body.append(f"    \\pgfmathsetmacro{{\\px}}{{{xs}+\\col*{xstep}+\\isoddr*({xstep}/2)}}")
        else:
            body.append(f"    \\pgfmathsetmacro{{\\px}}{{{xs}+\\col*{xstep}}}")
        body.append(f"    \\pgfmathsetmacro{{\\py}}{{{ys}+\\row*{ystep}}}")
        body += color_block(f"\\fill[COLOR] (\\px,\\py) circle [radius={r}cm];")

    elif pt == "rect_grid":
        if "width" not in el or "height" not in el:
            raise ValueError("rect_grid pattern requires 'width' and 'height'")
        w     = _fmt(el["width"])
        h     = _fmt(el["height"])
        angle = el.get("rotation", 0)
        if stagger:
            body.append(f"    \\pgfmathsetmacro{{\\rx}}{{{xs}+\\col*{xstep}+\\isoddr*({xstep}/2)}}")
        else:
            body.append(f"    \\pgfmathsetmacro{{\\rx}}{{{xs}+\\col*{xstep}}}")
        body.append(f"    \\pgfmathsetmacro{{\\ry}}{{{ys}+\\row*{ystep}}}")
        if angle:
            body.append(f"    \\pgfmathsetmacro{{\\cx}}{{\\rx+{w}/2}}")
            body.append(f"    \\pgfmathsetmacro{{\\cy}}{{\\ry+{h}/2}}")
            tmpl = (f"\\fill[COLOR, rotate around={{{_fmt(angle)}:(\\cx,\\cy)}}]"
                    f" (\\rx,\\ry) rectangle ({{\\rx+{w}}},{{\\ry+{h}}});")
        else:
            tmpl = f"\\fill[COLOR] (\\rx,\\ry) rectangle ({{\\rx+{w}}},{{\\ry+{h}}});"
        body += color_block(tmpl)

    else:
        raise ValueError(f"Unknown pattern_type: {pt!r}")

    body.append("  }")
    body.append("}")

    return "\n".join(body)


# ─── Dispatch table ───────────────────────────────────────────────────────────

_EMITTERS = {
    "background": _emit_background,
    "rectangle":  _emit_rectangle,
    "triangle":   _emit_triangle,
    "circle":     _emit_circle,
    "line":       _emit_line,
    "pattern":    _emit_pattern,
}

# ─── Public API ───────────────────────────────────────────────────────────────

def convert(source: "str | Path", output_path: Path = _DEFAULT_OUT) -> Path:
    """
    Validate *source* and write the TikZ macro to *output_path*.

    Parameters
    ----------
    source : str or Path
        Path to a Canvas AST JSON file, or a raw JSON string.
    output_path : Path
        Destination .tex file. Default: styles/versatus-dynamic-cover.tex.

    Returns
    -------
    Path
        The path of the written .tex file.

    Raises
    ------
    jsonschema.ValidationError
        If the input does not conform to canvas_schema.json.
    """
    # ── Load ──────────────────────────────────────────────────────────────────
    raw = source if isinstance(source, str) and source.strip().startswith("{") \
          else Path(source).read_text(encoding="utf-8")
    data = json.loads(raw)

    # ── Validate ──────────────────────────────────────────────────────────────
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=schema)

    elements = data["elements"]

    # ── Build colour definitions for every unique hex value ───────────────────
    hex_map = _build_hex_map(elements)

    # ── Assemble TikZ lines ───────────────────────────────────────────────────
    body_lines: list[str] = []

    # \definecolor declarations (must precede tikzpicture)
    for h6, name in sorted(hex_map.items(), key=lambda kv: kv[1]):
        body_lines.append(rf"  \definecolor{{{name}}}{{HTML}}{{{h6}}}")
    if hex_map:
        body_lines.append("")

    # tikzpicture — x=1cm,y=-1cm maps bare numbers to centimetres with
    # y increasing downward; shift to page.north west sets (0,0) at the
    # top-left corner, matching how VLMs naturally perceive image coordinates.
    body_lines.append(
        r"  \begin{tikzpicture}["
        r"remember picture, overlay, "
        r"x=1cm, y=-1cm, "
        r"shift={(current page.north west)}"
        r"]"
    )

    for el in elements:
        emitter = _EMITTERS.get(el["type"])
        if emitter:
            # pattern emitter returns multi-line TikZ; indent each line
            rendered = emitter(el, hex_map)
            for line in rendered.splitlines():
                body_lines.append(f"    {line}")

    body_lines.append(r"  \end{tikzpicture}")

    # ── Wrap in \newcommand macro ─────────────────────────────────────────────
    inner = "\n".join(body_lines)
    macro = (
        "% Auto-generated by json_to_tikz.py — DO NOT EDIT MANUALLY\n"
        "\\newcommand{\\RenderDynamicCover}{%\n"
        f"{inner}\n"
        "}%\n"
    )

    # ── Write ─────────────────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(macro, encoding="utf-8")
    return output_path


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {Path(__file__).name} <canvas.json> [output.tex]")
        sys.exit(1)

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else _DEFAULT_OUT

    try:
        out = convert(src, dst)
        print(f"[OK] TikZ macro written to: {out}")
    except jsonschema.ValidationError as exc:
        print(f"[SCHEMA ERROR] {exc.path} → {exc.message}", file=sys.stderr)
        sys.exit(2)
    except FileNotFoundError as exc:
        print(f"[FILE ERROR] {exc}", file=sys.stderr)
        sys.exit(3)
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(4)
