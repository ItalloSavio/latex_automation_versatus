#!/usr/bin/env python3
"""
svg_to_tikz.py — Pure-Python SVG -> TikZ converter for brand logos.

No Inkscape, no GTK/pygobject. Uses `svgelements` (pure Python, pip-only)
to parse SVG geometry (paths, polygons, beziers, arcs, CSS classes) and
emits a positionable TikZ macro.

Why not svg2tikz / Inkscape:
    svg2tikz depends on pygobject (GTK), which requires a native toolchain
    that is painful to install on Windows and varies machine to machine.
    This script has zero native dependencies — `pip install svgelements`
    is enough anywhere the automation runs.

Output macro shape:
    \\newcommand{\\<MacroName>}[1]{%
      \\begingroup
      \\definecolor{<prefix>0}{HTML}{...}
      ...
      \\begin{scope}[shift={#1}]
        \\fill[<prefix>0] (x,y) -- (x2,y2) .. controls (..) and (..) .. (x3,y3) -- cycle;
        ...
      \\end{scope}
      \\endgroup
    }

Usage:
    python svg_to_tikz.py <logo.svg> <MacroName> [output.tikz] [--height CM]

    # Used by convert_logos.py to batch-convert a whole brand:
    python svg_to_tikz.py brands/versatus/logos/svg/logo_dark.svg LogoVersatusDark \\
        brands/versatus/logos/logo_dark.tikz --height 3
"""

import argparse
import sys
from pathlib import Path

ROUND = 3
ARC_SAMPLES = 16   # line-segments used to approximate one SVG arc


def _fmt(n: float) -> str:
    return f"{round(n, ROUND):g}"


def _hex_no_alpha(color) -> str:
    """svgelements Color -> 6-digit hex string, alpha stripped."""
    h = color.hexrgb if hasattr(color, "hexrgb") else str(color)
    h = h.lstrip("#")
    return h[:6].upper()


def _convert_quad_to_cubic(p0, p1, p2):
    """Quadratic bezier (p0,p1,p2) -> cubic control points (c1,c2)."""
    c1x = p0[0] + 2 / 3 * (p1[0] - p0[0])
    c1y = p0[1] + 2 / 3 * (p1[1] - p0[1])
    c2x = p2[0] + 2 / 3 * (p1[0] - p2[0])
    c2y = p2[1] + 2 / 3 * (p1[1] - p2[1])
    return (c1x, c1y), (c2x, c2y)


def _shape_fill_rule(shape) -> str | None:
    rule = None
    try:
        rule = shape.values.get("fill-rule")
    except AttributeError:
        pass
    return rule


def _path_to_tikz_subpaths(shape, to_tikz_xy):
    """
    Walk a Path's segments (already transformed to SVG user space) and
    emit one TikZ coordinate-path string per SVG subpath (Move..Close).
    Multiple subpaths are combined later into a single \\fill so that
    nonzero/evenodd winding correctly produces letterform holes.
    """
    from svgelements import Move, Close, Line, CubicBezier, QuadraticBezier, Arc

    segments = list(shape.segments(transformed=True))
    subpaths: list[str] = []
    current: list[str] = []
    cursor = None

    def flush():
        nonlocal current
        if current:
            subpaths.append(" ".join(current))
            current = []

    for seg in segments:
        if isinstance(seg, Move):
            flush()
            cursor = (seg.end.x, seg.end.y)
            x, y = to_tikz_xy(*cursor)
            current.append(f"({_fmt(x)},{_fmt(y)})")

        elif isinstance(seg, Line):
            cursor = (seg.end.x, seg.end.y)
            x, y = to_tikz_xy(*cursor)
            current.append(f"-- ({_fmt(x)},{_fmt(y)})")

        elif isinstance(seg, CubicBezier):
            c1 = to_tikz_xy(seg.control1.x, seg.control1.y)
            c2 = to_tikz_xy(seg.control2.x, seg.control2.y)
            end = to_tikz_xy(seg.end.x, seg.end.y)
            current.append(
                f".. controls ({_fmt(c1[0])},{_fmt(c1[1])}) and "
                f"({_fmt(c2[0])},{_fmt(c2[1])}) .. ({_fmt(end[0])},{_fmt(end[1])})"
            )
            cursor = (seg.end.x, seg.end.y)

        elif isinstance(seg, QuadraticBezier):
            p0 = (seg.start.x, seg.start.y)
            p1 = (seg.control.x, seg.control.y)
            p2 = (seg.end.x, seg.end.y)
            c1, c2 = _convert_quad_to_cubic(p0, p1, p2)
            c1t = to_tikz_xy(*c1)
            c2t = to_tikz_xy(*c2)
            endt = to_tikz_xy(*p2)
            current.append(
                f".. controls ({_fmt(c1t[0])},{_fmt(c1t[1])}) and "
                f"({_fmt(c2t[0])},{_fmt(c2t[1])}) .. ({_fmt(endt[0])},{_fmt(endt[1])})"
            )
            cursor = p2

        elif isinstance(seg, Arc):
            # Sample the arc as straight segments (robust across svgelements versions).
            for i in range(1, ARC_SAMPLES + 1):
                t = i / ARC_SAMPLES
                pt = seg.point(t)
                x, y = to_tikz_xy(pt.x, pt.y)
                current.append(f"-- ({_fmt(x)},{_fmt(y)})")
            cursor = (seg.end.x, seg.end.y)

        elif isinstance(seg, Close):
            current.append("-- cycle")

    flush()
    return subpaths


def _polygon_to_tikz(shape, to_tikz_xy) -> str:
    pts = []
    for x, y in shape.points:
        tx, ty = to_tikz_xy(x, y)
        pts.append(f"({_fmt(tx)},{_fmt(ty)})")
    return " -- ".join(pts) + " -- cycle"


def convert(
    svg_path: Path,
    macro_name: str,
    target_height_cm: float = 3.0,
) -> str:
    """Returns the full LaTeX macro definition as a string."""
    from svgelements import SVG, Path as SvgPath, Polygon, Polyline, Rect, Circle, Ellipse

    svg = SVG.parse(str(svg_path))
    shapes = [
        el for el in svg.elements()
        if isinstance(el, (SvgPath, Polygon, Polyline, Rect, Circle, Ellipse))
    ]
    if not shapes:
        raise ValueError(f"Nenhuma forma vetorial encontrada em {svg_path}")

    # ── overall bounding box (drives normalization) ────────────────────────
    xs: list[float] = []
    ys: list[float] = []
    for shape in shapes:
        bbox = shape.bbox()
        if bbox:
            xs += [bbox[0], bbox[2]]
            ys += [bbox[1], bbox[3]]

    if not xs:
        raise ValueError(f"Nao foi possivel calcular bounding box de {svg_path}")

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    svg_height = y_max - y_min
    if svg_height <= 0:
        raise ValueError(f"Altura invalida no SVG: {svg_path}")

    scale = target_height_cm / svg_height

    def to_tikz_xy(x: float, y: float) -> tuple[float, float]:
        # Normalize to bbox origin, flip Y (SVG is y-down, TikZ logo space is y-up).
        return (x - x_min) * scale, (y_max - y) * scale

    # ── color table ──────────────────────────────────────────────────────
    color_prefix = "".join(c for c in macro_name if c.isalnum()) + "C"
    color_index: dict[str, str] = {}     # hex -> tikz color name
    color_defs: list[str] = []

    def color_name_for(hexval: str) -> str:
        if hexval not in color_index:
            name = f"{color_prefix}{len(color_index)}"
            color_index[hexval] = name
            color_defs.append(f"\\definecolor{{{name}}}{{HTML}}{{{hexval}}}")
        return color_index[hexval]

    # ── shape emission (preserve SVG paint order) ───────────────────────────
    body_lines: list[str] = []
    skipped = 0

    for shape in shapes:
        fill = getattr(shape, "fill", None)
        is_filled = fill is not None and str(fill).lower() not in ("none", "")

        if isinstance(shape, SvgPath):
            subpaths = _path_to_tikz_subpaths(shape, to_tikz_xy)
            if not subpaths:
                continue
            if not is_filled:
                skipped += 1
                continue
            cname = color_name_for(_hex_no_alpha(fill))
            rule = _shape_fill_rule(shape)
            opt = f"{cname}, even odd rule" if rule == "evenodd" else cname
            path_expr = " ".join(subpaths)
            body_lines.append(f"\\fill[{opt}] {path_expr};")

        elif isinstance(shape, (Polygon, Polyline)):
            if not is_filled or len(shape.points) < 3:
                skipped += 1
                continue
            cname = color_name_for(_hex_no_alpha(fill))
            body_lines.append(f"\\fill[{cname}] {_polygon_to_tikz(shape, to_tikz_xy)};")

        elif isinstance(shape, Rect):
            if not is_filled:
                skipped += 1
                continue
            cname = color_name_for(_hex_no_alpha(fill))
            x0, y0 = to_tikz_xy(shape.x, shape.y)
            x1, y1 = to_tikz_xy(shape.x + shape.width, shape.y + shape.height)
            body_lines.append(
                f"\\fill[{cname}] ({_fmt(x0)},{_fmt(y1)}) rectangle ({_fmt(x1)},{_fmt(y0)});"
            )

        elif isinstance(shape, (Circle, Ellipse)):
            if not is_filled:
                skipped += 1
                continue
            cname = color_name_for(_hex_no_alpha(fill))
            cx, cy = to_tikz_xy(shape.cx, shape.cy)
            rx = shape.rx * scale
            ry = shape.ry * scale if isinstance(shape, Ellipse) else rx
            body_lines.append(
                f"\\fill[{cname}] ({_fmt(cx)},{_fmt(cy)}) ellipse "
                f"[x radius={_fmt(rx)}, y radius={_fmt(ry)}];"
            )

    if not body_lines:
        raise ValueError(
            f"Nenhuma forma preenchida (fill) encontrada em {svg_path} "
            f"({skipped} formas sem fill foram ignoradas)."
        )

    indent = "    "
    macro = (
        f"% Auto-generated from {svg_path.name} by svg_to_tikz.py - DO NOT EDIT MANUALLY\n"
        f"\\newcommand{{\\{macro_name}}}[1]{{%\n"
        f"{indent}\\begingroup\n"
        + "".join(f"{indent}{d}\n" for d in color_defs)
        + f"{indent}\\begin{{scope}}[shift={{#1}}]\n"
        + "".join(f"{indent}{indent}{line}\n" for line in body_lines)
        + f"{indent}\\end{{scope}}\n"
        f"{indent}\\endgroup\n"
        f"}}\n"
    )
    return macro


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="svg_to_tikz.py",
        description="Converte um SVG de logo em uma macro TikZ posicionavel (sem Inkscape/GTK)."
    )
    parser.add_argument("svg", help="Caminho do arquivo .svg")
    parser.add_argument("macro_name", help="Nome da macro LaTeX (ex: LogoVersatusDark)")
    parser.add_argument("output", nargs="?", help="Arquivo .tikz de saida (default: stdout)")
    parser.add_argument("--height", type=float, default=3.0, help="Altura alvo em cm (default: 3.0)")
    args = parser.parse_args()

    svg_path = Path(args.svg).resolve()
    if not svg_path.exists():
        print(f"[ERRO] SVG nao encontrado: {svg_path}", file=sys.stderr)
        return 1

    try:
        macro = convert(svg_path, args.macro_name, args.height)
    except Exception as exc:
        print(f"[ERRO] Falha ao converter {svg_path.name}: {exc}", file=sys.stderr)
        return 2

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(macro, encoding="utf-8")
        print(f"[OK] {svg_path.name} -> {out_path}  (\\{args.macro_name}{{<x,y>}})")
    else:
        print(macro)

    return 0


if __name__ == "__main__":
    sys.exit(main())
