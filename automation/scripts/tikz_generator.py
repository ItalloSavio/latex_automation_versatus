#!/usr/bin/env python3
"""
tikz_generator.py — Deterministic TikZ from cover_analysis.json.

Converts the structured analysis produced by cover_assembler into a
LuaLaTeX-ready \\newcommand{\\RenderDynamicCover}{...} block with no LLM
involvement. Every coordinate and color comes from the JSON measurements.

Shape dispatch:
  rectangle      → \\fill[c] (x,y) rectangle (x+w,y+h)
  rounded_rect   → same, with `rounded corners=radius_cm`
  circle         → \\fill[c] (cx,cy) circle (r)   [r = min(w,h)/2]
  ellipse        → \\fill[c] (cx,cy) ellipse (w/2 and h/2)
  triangle       → three vertices from `points_cm`, or the bbox corner named by
                   `orientation` (ul/ur/bl/lr); a triangle carrying NEITHER is a grid
                   diagonal CELL and takes its orientation from its partner half
  polygon        → `points_cm` vertices; bbox rectangle only when no vertices given
  annulus_sector → ring wedge (r_in=0 degenerates to a pie slice)
  circle_lattice → tiled op-art circles + accent lenses
  hatch          → optional base fill + \\foreach of parallel lines

Text carries `rotation_deg` for vertical/angled type.

Every shape above is SELF-CONTAINED: it draws from its own fields alone. The one
exception is the unoriented triangle, kept for the grid's paired diagonal cells.

Pattern dispatch:
  regions tagged with pattern=grid/v_stripes → \\foreach loop
  untagged regions                           → individual \\fill

Public API:
    generate(analysis, output_path=None) -> str
"""

import json
import math
from pathlib import Path

_HERE       = Path(__file__).resolve().parent
_OUTPUT_DIR = _HERE.parent / "output"

# Maximum RGB Euclidean distance to consider two colors "the same palette entry"
_COLOR_MATCH_DIST = 35.0

# Adjacent \fill polygons share an exact edge; the rasterizer antialiases each
# fill against the background independently, leaving a hairline of background
# bleeding through the seam. Stroking every fill with its OWN colour by this
# width makes neighbours overlap by half of it, closing the seam. Kept small
# (well under 1px at 150 dpi ≈ 0.48pt) so block sizes shift imperceptibly.
_SEAM_BLEED_PT = 0.5


def _fill_opts(color: str) -> str:
    """Fill option string that also strokes the outline in the same colour."""
    return f"{color},draw={color},line width={_SEAM_BLEED_PT}pt,line join=miter"

# ─── Text rendering calibration ───────────────────────────────────────────────
# Swiss-design covers set Helvetica with tight tracking; the render fallback
# (TeX Gyre Heros / Arial) comes out wider, so text is compressed horizontally.
# This is only a COLD-START prior — calibrator.py measures each element's render
# and writes a per-element `hscale` that overrides it, so the value need not be
# exact and the pipeline self-adapts to any font. (Proven: starting from 1.0 the
# loop climbs back on its own.)
_TEXT_HSCALE = 0.89

# EasyOCR boxes sit slightly below the true baseline (they include descender
# padding), and an `anchor=south west` node adds its own inner-sep + font depth.
# Net, glyphs render low; raising the anchor by this fraction of the em height
# re-aligns the visual baseline with the original. Derived from font geometry
# (0.159·em OCR descent − 0.068·em node lift ≈ 0.091·em) so it scales with size.
_TEXT_YCORR_EM = 0.091
_PT_PER_CM     = 28.35

# The OCR x is the ink-left, but a base-west node's west edge is the glyph
# origin — the first letter's left side bearing pushes the ink ≈0.043·em to the
# right of it. Shift the node left by that (× hscale) so ink-left meets ink-left.
_TEXT_XSB_EM   = 0.043


# ─── Public API ───────────────────────────────────────────────────────────────

def generate(
    analysis:    "dict | str | Path",
    output_path: "str | Path | None" = None,
) -> str:
    """
    Generate a \\newcommand{\\RenderDynamicCover}{...} TikZ block.

    Parameters
    ----------
    analysis    : cover_analysis dict or path to cover_analysis.json
    output_path : where to write the .tikz file. Default: automation/output/replicated_cover.tikz

    Returns
    -------
    str — the complete TikZ block (also written to output_path)
    """
    if isinstance(analysis, (str, Path)):
        p = Path(analysis)
        analysis = json.loads(p.read_text(encoding="utf-8"))

    tikz = _build_tikz(analysis)

    out = Path(output_path).resolve() if output_path else (
        _OUTPUT_DIR / "replicated_cover.tikz"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(tikz, encoding="utf-8")
    print(f"    [TikZ] → {out}  ({len(tikz)} chars)")
    return tikz


# ─── Main builder ─────────────────────────────────────────────────────────────

def _build_tikz(doc: dict) -> str:
    canvas  = doc.get("canvas", {"width_cm": 21.0, "height_cm": 29.7})
    W       = canvas.get("width_cm",  21.0)
    H       = canvas.get("height_cm", 29.7)
    colors  = doc.get("colors",        [])
    regions = doc.get("regions",       [])
    texts   = doc.get("text_elements", [])
    pkg     = doc.get("typography", {}).get("dominant_latex_pkg", "helvet")

    # Build color name map: HEX_UPPER → "c0" / "t0"
    color_map, color_defs = _build_color_map(colors, texts)

    lines = [
        f"% TikZ generated by tikz_generator.py from cover_analysis.json",
        f"% Required preamble: \\usepackage[T1]{{fontenc}}\\usepackage{{{pkg}}}\\usepackage{{graphicx}}",
        f"% Canvas: {W} x {H} cm ({canvas.get('format','Custom')})",
        r"\newcommand{\RenderDynamicCover}{%",
    ]

    # Color definitions
    lines += color_defs
    lines.append("")

    # Background color hex (most-coverage = c0)
    bg_hex = colors[0]["hex"].lstrip("#").upper() if colors else "FFFFFF"

    # Canvas fill (background = full rectangle, always first)
    lines.append(r"  \begin{tikzpicture}[x=1cm, y=1cm]")
    # Clip to the page: the per-fill seam bleed (draw=) extends shapes a hair
    # past the edges, which would enlarge the bounding box and overflow onto a
    # second (blank) page. Clipping locks the box to WxH and trims the overhang.
    lines.append(f"  \\clip (0,0) rectangle ({_f(W)},{_f(H)});")
    lines.append(f"  % Background canvas")
    if color_map:
        bg_color = list(color_map.values())[0]  # most-coverage color = background
        lines.append(f"  \\fill[{bg_color}] (0,0) rectangle ({_f(W)},{_f(H)});")
    lines.append("")

    # Geometric regions
    lines.append("  % Geometric regions")
    region_lines, _ = _build_regions(regions, color_map, W, H)
    lines += region_lines
    lines.append("")

    # Text elements
    if texts:
        lines.append("  % Text elements")
        lines += _build_text_nodes(_resolve_text_overlap(texts), color_map, bg_hex, W)
        lines.append("")

    lines.append(r"  \end{tikzpicture}%")
    lines.append(r"}%")

    return "\n".join(lines) + "\n"


# ─── Color map ────────────────────────────────────────────────────────────────

def _build_color_map(
    colors:  list,
    texts:   list,
) -> "tuple[dict[str,str], list[str]]":
    """
    Build {HEX_UPPER: name} map and the corresponding \\definecolor lines.

    Region palette colors → c0, c1, …
    Text-only colors not in palette → t0, t1, …
    """
    color_map: dict[str, str] = {}
    defs: list[str] = []

    defs.append("  % Color palette (K-means from CV)")
    for i, c in enumerate(colors):
        h    = c["hex"].lstrip("#").upper()
        name = f"c{i}"
        color_map[h] = name
        cov  = c.get("coverage", 0) * 100
        defs.append(f"  \\definecolor{{{name}}}{{HTML}}{{{h}}}  % {cov:.1f}% coverage")

    # Text colors not already in palette
    t_idx = 0
    defs.append("  % Text colors")
    for el in texts:
        th = el.get("color_hex", "#000000").lstrip("#").upper()
        if th not in color_map:
            matched = _nearest_color(th, color_map)
            if matched is None:
                name = f"t{t_idx}"
                t_idx += 1
                color_map[th] = name
                defs.append(f"  \\definecolor{{{name}}}{{HTML}}{{{th}}}")
            else:
                color_map[th] = matched

    return color_map, defs


def _nearest_color(hex_target: str, color_map: "dict[str,str]") -> "str | None":
    """Return the name of the nearest palette color if within _COLOR_MATCH_DIST."""
    r0, g0, b0 = _hex_to_rgb(hex_target)
    best_name = None
    best_dist = _COLOR_MATCH_DIST + 1
    for h, name in color_map.items():
        r, g, b = _hex_to_rgb(h)
        d = math.sqrt((r-r0)**2 + (g-g0)**2 + (b-b0)**2)
        if d < best_dist:
            best_dist = d
            best_name = name
    return best_name if best_dist <= _COLOR_MATCH_DIST else None


def _hex_to_rgb(h: str) -> "tuple[int,int,int]":
    h = h.lstrip("#").upper()
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ─── Region rendering ─────────────────────────────────────────────────────────

def _build_regions(
    regions:   list,
    color_map: dict,
    W: float,
    H: float,
) -> "tuple[list[str], set[int]]":
    """
    Generate \\fill / \\foreach commands for all regions.
    Returns (lines, consumed_indices).
    """
    # The photographed poster's paper MARGIN trims everything, so it must be painted last —
    # otherwise a VLM `region.add` (appended after the analysis was built) covers it and the
    # frame silently does nothing. Stable partition: every other region keeps its order.
    regions = ([r for r in regions if r.get("source") != "margin"]
               + [r for r in regions if r.get("source") == "margin"])
    lines: list[str] = []
    consumed: set[int] = set()

    # ── Pass 1: pattern groups → \foreach ──────────────────────────────────
    groups: dict[str, list[int]] = {}
    for i, r in enumerate(regions):
        if "pattern" not in r:
            continue
        # The \foreach shortcut TILES RECTANGLES — it emits `rectangle` unconditionally.
        # A circle/triangle that picked up a pattern must NOT come through here, or it
        # renders as a box (and often at the pattern's mirror anchor, off its real spot).
        # Let it fall to Pass 3, which draws each shape at its own bbox, correctly.
        if r.get("shape_type", "rectangle") not in ("rectangle", "polygon"):
            continue
        # The page MARGIN is a frame, never a repeat. `pattern_detector` sees two thin
        # look-alike bars (left and right edge) and groups them into a \foreach with a
        # nonsense period, tiling them off-canvas — so the frame silently loses two sides.
        # Same failure family as the circle-drawn-as-rectangle bug.
        if r.get("source") == "margin":
            continue
        anch  = r.get("foreach_anchor", {})
        key   = (
            r.get("color_hex", ""),
            r.get("foreach_axis", "x"),
            f"{anch.get('x',0):.3f},{anch.get('y',0):.3f}",
        )
        groups.setdefault(str(key), []).append(i)

    for key_str, idxs in groups.items():
        first    = regions[idxs[0]]
        anch     = first.get("foreach_anchor", first["bbox_cm"])
        axis     = first.get("foreach_axis", "x")
        step     = first.get("foreach_step_cm", 0.0)
        count    = first.get("foreach_count", len(idxs))
        col_name = _color_name(first, color_map)
        bx, by   = _f(anch["x"]),         _f(anch["y"])
        bw, bh   = _f(anch.get("w", first["bbox_cm"]["w"])), \
                   _f(anch.get("h", first["bbox_cm"]["h"]))
        st       = _f(step)
        n        = count - 1

        if axis == "x":
            lines.append(
                f"  \\foreach \\i in {{0,...,{n}}} {{"
                f"\\fill[{_fill_opts(col_name)}] ({bx}+\\i*{st},{by}) "
                f"rectangle ({bx}+\\i*{st}+{bw},{by}+{bh}); }}"
            )
        else:  # y
            lines.append(
                f"  \\foreach \\i in {{0,...,{n}}} {{"
                f"\\fill[{_fill_opts(col_name)}] ({bx},{by}+\\i*{st}) "
                f"rectangle ({bx}+{bw},{by}+\\i*{st}+{bh}); }}"
            )
        consumed.update(idxs)

    # ── Pass 2: detect overlapping triangle pairs ───────────────────────────
    # A SELF-CONTAINED triangle (explicit vertices, or a named corner of its own bbox) is
    # excluded from pairing: it already knows its orientation, so letting it be someone's
    # partner would draw it twice — once by itself, once by the pair.
    tri_indices = [
        i for i, r in enumerate(regions)
        if r.get("shape_type") == "triangle" and i not in consumed
        and not _tri_self_described(r)
    ]
    tri_pairs: dict[int, int] = {}  # index → partner index
    for i in range(len(tri_indices)):
        for j in range(i + 1, len(tri_indices)):
            a, b = tri_indices[i], tri_indices[j]
            if _bbox_iou(regions[a]["bbox_cm"], regions[b]["bbox_cm"]) > 0.5:
                tri_pairs[a] = b
                tri_pairs[b] = a

    # ── Pass 3: individual regions ──────────────────────────────────────────
    tri_done: set[int] = set()
    for i, r in enumerate(regions):
        if i in consumed:
            continue
        shape    = r.get("shape_type", "rectangle")
        col_name = _color_name(r, color_map)
        bx       = r["bbox_cm"]

        if shape == "polygon" and r.get("points_cm"):
            lines.append(_cmd_polygon(col_name, r["points_cm"]))

        elif shape == "rectangle" or shape == "polygon":
            lines.append(_cmd_rect(col_name, bx))

        elif shape == "circle":
            lines.append(_cmd_circle(col_name, bx))

        elif shape == "ellipse":
            lines.append(_cmd_ellipse(col_name, bx))

        elif shape == "rounded_rect":
            lines.append(_cmd_rounded_rect(col_name, bx, r.get("radius_cm", 0.0)))

        elif shape == "annulus_sector":      # one coloured wedge of a ring (see _cmd_*)
            cx = bx["x"] + bx["w"] / 2
            cy = bx["y"] + bx["h"] / 2
            lines.append(_cmd_annulus_sector(
                col_name, cx, cy, r.get("r_in_cm", 0.0), min(bx["w"], bx["h"]) / 2,
                r.get("angle0_deg", 0.0), r.get("angle1_deg", 360.0)))

        elif shape == "circle_lattice":     # op-art: tiled circles + accent lenses
            col_b = _color_name({"color_hex": r.get("color_b_hex", "#FFFFFF")}, color_map)
            lens  = _color_name({"color_hex": r.get("lens_hex", "#FFFFFF")}, color_map)
            lines.append(_cmd_circle_lattice(
                col_name, col_b, lens, r.get("period_cm", 5.0), r.get("radius_cm", 3.5),
                r.get("lens_w_cm", 2.5), r.get("lens_h_cm", 1.2), W, H,
                r.get("phase_x_cm", 0.0), r.get("phase_y_cm", 0.0)))

        elif shape == "hatch":
            base = (_color_name({"color_hex": r["base_hex"]}, color_map)
                    if r.get("base_hex") else None)
            lines.append(_cmd_hatch(col_name, base, bx, r.get("period_cm", 0.2),
                                    r.get("line_width_pt", 0.8), r.get("direction", "v")))

        elif shape == "triangle":
            # Self-contained first: a triangle that carries its own vertices or corner name
            # draws itself. The paired path below exists for the grid's diagonal CELLS, which
            # only know their orientation from the partner half — that dependency is why a
            # lone triangle used to land on a guessed corner (capa18: 86 of them, half mirrored).
            if _tri_self_described(r):
                pts = r.get("points_cm")
                if pts and len(pts) == 3:
                    lines.append(_cmd_polygon(col_name, pts))
                else:
                    lines.append(_TRI_CMD[r["orientation"]](col_name, bx))
                continue
            if i in tri_done:
                continue
            partner = tri_pairs.get(i)
            if partner is not None and partner not in consumed:
                col_a     = col_name
                col_b     = _color_name(regions[partner], color_map)
                bx_b      = regions[partner]["bbox_cm"]
                diag_type = r.get("diagonal_type", "slash")
                if diag_type == "backslash":
                    # \ diagonal: first region = NW (lower-left in TikZ),
                    #             second region = SE (upper-right in TikZ)
                    lines.append(_cmd_triangle_bl(col_a, bx))
                    lines.append(_cmd_triangle_ur(col_b, bx_b))
                else:
                    # / diagonal: first region = UL, second = LR
                    lines.append(_cmd_triangle_ul(col_a, bx))
                    lines.append(_cmd_triangle_lr(col_b, bx_b))
                tri_done.add(partner)
            else:
                lines.append(_cmd_triangle_ul(col_name, bx))

    return lines, consumed


# ─── Shape commands ───────────────────────────────────────────────────────────

def _cmd_rect(color: str, b: dict) -> str:
    x1, y1 = _f(b["x"]),          _f(b["y"])
    x2, y2 = _f(b["x"] + b["w"]), _f(b["y"] + b["h"])
    return f"  \\fill[{_fill_opts(color)}] ({x1},{y1}) rectangle ({x2},{y2});"


def _cmd_circle(color: str, b: dict) -> str:
    cx = _f(b["x"] + b["w"] / 2)
    cy = _f(b["y"] + b["h"] / 2)
    r  = _f(min(b["w"], b["h"]) / 2)
    return f"  \\fill[{_fill_opts(color)}] ({cx},{cy}) circle ({r}cm);"


def _cmd_circle_lattice(col_a: str, col_b: str, lens: str, p: float, r: float,
                        lw: float, lh: float, W: float, H: float,
                        phx: float = 0.0, phy: float = 0.0) -> str:
    """Op-art circle lattice: a checkerboard of two circle colours tiled at period `p`,
    plus horizontal accent LENSES at the vertical seams. A parametric VISUAL primitive —
    period/radius/colours/lens size/phase are DATA (measured from the image), so it grows
    the vocabulary without new code. Renders bottom (col_b bg) → circles → lenses on top.
    `phx`/`phy` shift the grid so the circles land on the original's (measured phase)."""
    p = max(0.5, p)
    nx = int(W / p) + 2
    ny = int(H / p) + 2
    out = [f"  \\fill[{col_b}] (0,0) rectangle ({_f(W)},{_f(H)});"]
    for j in range(-1, ny):
        for i in range(-1, nx):
            col = col_a if (i + j) % 2 == 0 else col_b
            out.append(f"  \\fill[{col}] ({_f(phx+i*p)},{_f(phy+j*p)}) circle ({_f(r)});")
    # accent LENS = the vesica (intersection of two vertically-adjacent circles), clipped from a
    # slightly LARGER radius (lr) so neighbouring lenses MERGE at the diagonal centres into the
    # original's continuous horizontal chains — with the plain circle r they fell just short
    # (half-width 0.49p < 0.5p), leaving bg gaps that read as "inverted". lw/lh are unused.
    lr = round(r + 0.02 * p, 2)
    for j in range(-1, ny):
        for i in range(-1, nx):
            cx = _f(phx + i * p); cyl = _f(phy + j * p); cyh = _f(phy + (j + 1) * p)
            out.append(f"  \\begin{{scope}}\\clip ({cx},{cyl}) circle ({_f(lr)});"
                       f"\\fill[{lens}] ({cx},{cyh}) circle ({_f(lr)});\\end{{scope}}")
    return "\n".join(out)


def _cmd_annulus_sector(color: str, cx: float, cy: float, r0: float, r1: float,
                        a0: float, a1: float) -> str:
    """One wedge of a ring: outer arc a0→a1 at r1, back along the inner arc at r0.

    Bauhaus/Swiss covers build big discs out of these (capa1's ring is 2 rings × 4
    quadrants, each a different colour). A full disc is just r0=0, where the wedge
    degenerates to a pie slice through the centre — the same command covers both."""
    import math
    xa, ya = cx + r1 * math.cos(math.radians(a0)), cy + r1 * math.sin(math.radians(a0))
    if r0 <= 1e-6:
        return (f"  \\fill[{_fill_opts(color)}] ({_f(cx)},{_f(cy)}) -- ({_f(xa)},{_f(ya)}) "
                f"arc ({_f(a0)}:{_f(a1)}:{_f(r1)}cm) -- cycle;")
    xb, yb = cx + r0 * math.cos(math.radians(a1)), cy + r0 * math.sin(math.radians(a1))
    return (f"  \\fill[{_fill_opts(color)}] ({_f(xa)},{_f(ya)}) "
            f"arc ({_f(a0)}:{_f(a1)}:{_f(r1)}cm) -- ({_f(xb)},{_f(yb)}) "
            f"arc ({_f(a1)}:{_f(a0)}:{_f(r0)}cm) -- cycle;")


def _cmd_polygon(color: str, points_cm: list) -> str:
    """Parametric primitive: an arbitrary filled polygon from its vertices (cm, TikZ
    y-up). The general shape that lets a proposer express what the fixed primitives
    can't — it emits VERTICES (data), the renderer stays deterministic."""
    pts = " -- ".join(f"({_f(x)},{_f(y)})" for x, y in points_cm)
    return f"  \\fill[{_fill_opts(color)}] {pts} -- cycle;"


def _cmd_hatch(line_col: str, base_col: "str | None", b: dict,
               period: float, lw: float, direction: str) -> str:
    """Parallel-line hatch: an optional base fill + a \\foreach of thin lines. A parametric
    VISUAL primitive — direction/period/width/colours are DATA, so a proposer grows the
    vocabulary without new code. direction 'h' = horizontal lines, else vertical."""
    x1, y1 = _f(b["x"]), _f(b["y"])
    x2, y2 = _f(b["x"] + b["w"]), _f(b["y"] + b["h"])
    step   = max(0.03, period)
    lws    = _f(max(0.1, lw))
    out = []
    if base_col:
        out.append(f"  \\fill[{_fill_opts(base_col)}] ({x1},{y1}) rectangle ({x2},{y2});")
    if direction == "h":
        out.append(f"  \\foreach \\y in {{{y1},{_f(b['y'] + step)},...,{y2}}} "
                   f"{{\\draw[{line_col},line width={lws}pt] ({x1},\\y) -- ({x2},\\y);}}")
    else:
        out.append(f"  \\foreach \\x in {{{x1},{_f(b['x'] + step)},...,{x2}}} "
                   f"{{\\draw[{line_col},line width={lws}pt] (\\x,{y1}) -- (\\x,{y2});}}")
    return "\n".join(out)


def _cmd_triangle_ul(color: str, b: dict) -> str:
    """Upper-left triangle: (x,y) -- (x+w,y+h) -- (x,y+h) -- cycle"""
    x, y, w, h = b["x"], b["y"], b["w"], b["h"]
    return (
        f"  \\fill[{_fill_opts(color)}] "
        f"({_f(x)},{_f(y)}) -- "
        f"({_f(x+w)},{_f(y+h)}) -- "
        f"({_f(x)},{_f(y+h)}) -- cycle;"
    )


def _cmd_triangle_lr(color: str, b: dict) -> str:
    """Lower-right triangle (/ diagonal): BL -- BR -- TR -- cycle"""
    x, y, w, h = b["x"], b["y"], b["w"], b["h"]
    return (
        f"  \\fill[{_fill_opts(color)}] "
        f"({_f(x)},{_f(y)}) -- "
        f"({_f(x+w)},{_f(y)}) -- "
        f"({_f(x+w)},{_f(y+h)}) -- cycle;"
    )


def _cmd_triangle_ur(color: str, b: dict) -> str:
    """Upper-right triangle (\\ diagonal, SE region): TL -- TR -- BR -- cycle"""
    x, y, w, h = b["x"], b["y"], b["w"], b["h"]
    return (
        f"  \\fill[{_fill_opts(color)}] "
        f"({_f(x)},{_f(y+h)}) -- "
        f"({_f(x+w)},{_f(y+h)}) -- "
        f"({_f(x+w)},{_f(y)}) -- cycle;"
    )


def _cmd_triangle_bl(color: str, b: dict) -> str:
    """Lower-left triangle (\\ diagonal, NW region): TL -- BL -- BR -- cycle"""
    x, y, w, h = b["x"], b["y"], b["w"], b["h"]
    return (
        f"  \\fill[{_fill_opts(color)}] "
        f"({_f(x)},{_f(y+h)}) -- "
        f"({_f(x)},{_f(y)}) -- "
        f"({_f(x+w)},{_f(y)}) -- cycle;"
    )


# The four right triangles of a box, named by the corner they FILL (TikZ y-up).
_TRI_CMD = {
    "ul": _cmd_triangle_ul,
    "lr": _cmd_triangle_lr,
    "ur": _cmd_triangle_ur,
    "bl": _cmd_triangle_bl,
}


def _tri_self_described(r: dict) -> bool:
    """True when a triangle carries everything needed to draw it — three explicit vertices,
    or the name of the bbox corner it fills. Such a triangle never needs a partner region."""
    pts = r.get("points_cm")
    return bool((pts and len(pts) == 3) or r.get("orientation") in _TRI_CMD)


def _cmd_ellipse(color: str, b: dict) -> str:
    """Ellipse inscribed in the bbox. `circle` uses min(w,h), so an oblong bbox silently
    shrank to the shorter axis; an ellipse keeps both."""
    cx, cy = _f(b["x"] + b["w"] / 2), _f(b["y"] + b["h"] / 2)
    return (f"  \\fill[{_fill_opts(color)}] ({cx},{cy}) "
            f"ellipse ({_f(b['w']/2)}cm and {_f(b['h']/2)}cm);")


def _cmd_rounded_rect(color: str, b: dict, radius_cm: float) -> str:
    """Rounded-corner / stadium rectangle (capa10's bars). The radius is clamped to half the
    short side, where the shape degenerates into a stadium."""
    r = max(0.0, min(float(radius_cm), min(b["w"], b["h"]) / 2))
    x1, y1 = _f(b["x"]), _f(b["y"])
    x2, y2 = _f(b["x"] + b["w"]), _f(b["y"] + b["h"])
    return (f"  \\fill[{_fill_opts(color)}, rounded corners={_f(r)}cm] "
            f"({x1},{y1}) rectangle ({x2},{y2});")


# ─── Text nodes ───────────────────────────────────────────────────────────────

# Two lines only count as "overlapping" (and get pushed apart) when they share
# more than this fraction of the shorter box's height. OCR boxes run taller than
# the ink they contain, so adjacent lines routinely graze each other by a few
# percent; only a substantial overlap means the elements are truly stacked.
_OVERLAP_MIN_FRAC = 0.35


def _resolve_text_overlap(texts: list) -> list:
    """
    When two text elements share nearly the same Y baseline (within 0.15cm)
    but different X positions, they are on the same visual line — leave them.
    When they genuinely overlap in BOTH X and Y, push the lower one down
    by the minimum clearance needed.
    """
    if len(texts) <= 1:
        return texts

    # Work bottom-to-top so adjustments cascade correctly
    items = sorted(texts, key=lambda e: e["bbox_cm"]["y"])
    result = [items[0].copy()]

    for el in items[1:]:
        b = el["bbox_cm"]
        el_copy = {**el, "bbox_cm": {**b}}  # shallow copy

        for placed in result:
            pb = placed["bbox_cm"]
            # Vertical overlap in cm, then as a fraction of the shorter box.
            y_gap  = min(b["y"] + b["h"], pb["y"] + pb["h"]) - max(b["y"], pb["y"])
            y_frac = y_gap / max(min(b["h"], pb["h"]), 1e-6)
            y_overlap = y_frac > _OVERLAP_MIN_FRAC
            # X overlap?
            x_overlap = (b["x"] < pb["x"] + pb["w"]) and (b["x"] + b["w"] > pb["x"])

            if y_overlap and x_overlap:
                # Push el up so its bottom aligns with placed's top + 0.1cm gap
                clearance = pb["y"] + pb["h"] + 0.1
                shift     = clearance - b["y"]
                el_copy["bbox_cm"] = {**b, "y": round(clearance, 3)}
                # Rendering keys off the baseline, so move it by the same amount.
                if el_copy.get("baseline_y_cm") is not None:
                    el_copy["baseline_y_cm"] = round(el_copy["baseline_y_cm"] + shift, 3)
                break  # only adjust once per element

        result.append(el_copy)

    return sorted(result, key=lambda e: e["bbox_cm"]["y"])


def _build_text_nodes(texts: list, color_map: dict, bg_hex: str = "FFFFFF",
                      W: float = 21.0) -> "list[str]":
    bg_rgb = _hex_to_rgb(bg_hex)

    # Pre-build a reverse map: color name → hex, for contrast lookup
    name_to_hex = {v: k for k, v in color_map.items()}

    # Find the palette entry with maximum RGB distance from background
    best_contrast_name = _max_contrast_color(bg_rgb, color_map)

    lines = []
    for el in texts:
        text    = _escape_latex(el.get("text", ""))
        bx      = el["bbox_cm"]
        pt      = el.get("font_size_pt", 10.0)
        # OVERFLOW GUARD: shrink a font that would run off the canvas right edge (an OCR
        # mis-measure — e.g. capa1's title came out 126pt and bled off the page). Estimate
        # the line width at ~0.52 em per char; only shrinks genuinely off-canvas text.
        _raw  = el.get("text", "")
        _hs   = el.get("hscale", _TEXT_HSCALE)
        _avail = max(0.5, (W - bx["x"]) * 0.99)
        _estw  = len(_raw) * pt * 0.52 / _PT_PER_CM * _hs
        rot   = float(el.get("rotation_deg", 0.0) or 0.0)
        # the guard measures against the canvas RIGHT edge, which only bounds horizontal
        # text — rotated text runs down the other axis and must not be shrunk by it
        if _estw > _avail and abs(rot) < 1e-6:
            pt = max(6.0, round(pt * _avail / _estw, 1))
        leading = _f(round(pt * 1.2, 1))
        pt_str  = _f(pt)
        cmd     = el.get("latex_cmd",   r"\sffamily")
        weight  = el.get("weight_hint", "regular")

        # calibrator.py measures the render and writes these back per element.
        # They override the global defaults, which are only a cold-start guess.
        hscale_el = el.get("hscale", _TEXT_HSCALE)
        dx_cm     = el.get("dx_cm", 0.0)
        dy_cm     = el.get("dy_cm", 0.0)

        # Prefer the measured ink baseline: anchor the font baseline straight to
        # it (inner sep=0pt, no padding). Without ink metrics fall back to the
        # loose box bottom, lifted to compensate for node depth + inner sep.
        baseline = el.get("baseline_y_cm")
        if abs(rot) > 1e-6:
            # TikZ spins the node about its ANCHOR, so a rotation applied to an anchor that
            # was placed for horizontal type swings the whole block out of its box — which is
            # why the gate kept rejecting correct rotations. Re-anchor from the box instead.
            # At +90 (CCW, reading bottom-to-top) the text runs up (+y) and the ascenders
            # point at -x, so the baseline is the box's RIGHT edge; at -90 it mirrors.
            anchor = "base west"
            inner  = "inner sep=0pt, "
            if rot > 0:
                ax, ay = bx["x"] + bx["w"], bx["y"]
            else:
                ax, ay = bx["x"], bx["y"] + bx["h"]
            x, y = _f(round(ax + dx_cm, 3)), _f(round(ay + dy_cm, 3))
        elif baseline is not None:
            anchor = "base west"
            inner  = "inner sep=0pt, "
            x_sb   = bx["x"] - _TEXT_XSB_EM * (pt / _PT_PER_CM) * hscale_el
            x, y   = _f(round(x_sb + dx_cm, 3)), _f(round(baseline + dy_cm, 3))
        else:
            anchor = "south west"
            inner  = ""
            y_lift = bx["y"] + _TEXT_YCORR_EM * (pt / _PT_PER_CM)
            x, y   = _f(round(bx["x"] + dx_cm, 3)), _f(round(y_lift + dy_cm, 3))
        col_h   = el.get("color_hex", "#000000").lstrip("#").upper()
        col     = color_map.get(col_h, None)
        if col is None:
            matched = _nearest_color(col_h, color_map)
            col = matched if matched else best_contrast_name

        # Contrast check: if text color is too close to background, swap to
        # the most contrasting palette color so the text is always visible.
        resolved_hex = name_to_hex.get(col, col_h)
        if _rgb_dist(_hex_to_rgb(resolved_hex), bg_rgb) < 45:
            col = best_contrast_name

        bold = r"\bfseries " if weight == "bold" else " "

        hscale = _f(round(hscale_el, 4))
        rot_opt = f"rotate={_f(rot)}, " if abs(rot) > 1e-6 else ""
        lines.append(
            f"  \\node[anchor={anchor}, {rot_opt}{inner}text={col}] at ({x},{y})"
            f"{{\\scalebox{{{hscale}}}[1.0]{{{{\\fontsize{{{pt_str}pt}}{{{leading}pt}}"
            f"\\selectfont{cmd}{bold}{text}}}}}}};"
        )
    return lines


def _max_contrast_color(bg_rgb: "tuple[int,int,int]", color_map: dict) -> str:
    """Return the palette color name with maximum RGB distance from bg_rgb."""
    best_name = "black"
    best_dist = -1.0
    for h, name in color_map.items():
        d = _rgb_dist(_hex_to_rgb(h), bg_rgb)
        if d > best_dist:
            best_dist = d
            best_name = name
    return best_name


def _rgb_dist(a: "tuple[int,int,int]", b: "tuple[int,int,int]") -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _color_name(region: dict, color_map: dict) -> str:
    h = region.get("color_hex", "#000000").lstrip("#").upper()
    if h in color_map:
        return color_map[h]
    matched = _nearest_color(h, color_map)
    return matched if matched else "black"


def _bbox_iou(b1: dict, b2: dict) -> float:
    ax1, ay1 = b1["x"],            b1["y"]
    ax2, ay2 = b1["x"] + b1["w"],  b1["y"] + b1["h"]
    bx1, by1 = b2["x"],            b2["y"]
    bx2, by2 = b2["x"] + b2["w"],  b2["y"] + b2["h"]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter  = (ix2 - ix1) * (iy2 - iy1)
    union  = (ax2-ax1)*(ay2-ay1) + (bx2-bx1)*(by2-by1) - inter
    return inter / union if union > 0 else 0.0


def _escape_latex(text: str) -> str:
    """Escape characters that are special in LaTeX text mode."""
    subs = [
        ("\\", r"\textbackslash{}"),
        ("&",  r"\&"),
        ("%",  r"\%"),
        ("$",  r"\$"),
        ("#",  r"\#"),
        ("_",  r"\_"),
        ("{",  r"\{"),
        ("}",  r"\}"),
        ("~",  r"\textasciitilde{}"),
        ("^",  r"\textasciicircum{}"),
    ]
    for src, rep in subs:
        text = text.replace(src, rep)
    return text


def _f(v: float) -> str:
    """Format a float to at most 3 decimal places, stripping trailing zeros."""
    return f"{v:.3f}".rstrip("0").rstrip(".")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    _usage = (
        f"Uso: python {Path(__file__).name} [cover_analysis.json] [output.tikz]\n\n"
        "Converte cover_analysis.json em TikZ deterministico.\n"
        "Default: le automation/output/cover_analysis.json\n\n"
        "Exemplo:\n"
        "  python tikz_generator.py\n"
        "  python tikz_generator.py minha_analise.json saida.tikz"
    )

    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(_usage)
        sys.exit(0)

    _inp = sys.argv[1] if len(sys.argv) > 1 else str(_OUTPUT_DIR / "cover_analysis.json")
    _out = sys.argv[2] if len(sys.argv) > 2 else None

    if not Path(_inp).exists():
        print(f"[ERRO] Arquivo nao encontrado: {_inp}")
        print("Execute primeiro: python cover_assembler.py <imagem>")
        sys.exit(1)

    print(f"[TikZ] Gerando de: {_inp}")
    _result = generate(_inp, _out)

    print(f"\n--- Preview (primeiras 30 linhas) ---")
    for line in _result.split("\n")[:30]:
        print(line)
