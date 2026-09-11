"""Fase 7 — put OUR content into the replicated cover.

The replicator copies a Swiss poster faithfully; this module keeps that copy's geometry and
swaps the CONTENT for the book's own: the strings from `config/metadata.tex` and the brand
logo. Nothing about the copied design changes — position, size, weight, alignment, leading
and the whole colour palette stay exactly as measured from the original image. The user was
explicit that brand COLOURS are not wanted here: the poster's palette is the point.

Two decisions the user made, recorded because they are not derivable from the code:
  * text slots are filled by PRIORITY and whatever is left over KEEPS the string read from
    the image (rather than being deleted or filled with repeated fields);
  * the logo goes in the measured bbox when the analysis has one (only capa1/7/14 do) and
    otherwise in the emptiest measured zone.

  python automation/scripts/cover_integrator.py 19          # write integrated tikz for capa19
"""
import json

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Priority order: the biggest block on the cover becomes the title, and so on down.
_FIELD_ORDER = [
    "BookTitle", "BookSubtitle", "BookAuthor", "BookDescription",
    "BookSeries", "BookVersion", "BookDate", "BookConfidentiality",
]

_SAME_BLOCK_SIZE_TOL = 0.18   # two lines belong together when their pt sizes agree this well
_SAME_BLOCK_GAP_EM   = 2.2    # ...and their baselines sit within this many em of each other
_SAME_BLOCK_X_TOL_CM = 1.2    # ...and they share a left margin (Swiss layouts are flush-left)


def parse_metadata(path=None) -> dict:
    r"""Read \newcommand{\BookTitle}{...} pairs out of config/metadata.tex.

    Brace-matched rather than regex-to-end-of-line: \BookDate is \today and some values
    carry nested braces. Commands that take arguments (\providecommand with defaults) are
    ignored — only the zero-argument string macros are content.
    """
    path = Path(path) if path else ROOT / "config" / "metadata.tex"
    src = path.read_text(encoding="utf-8")
    head, out, pos = "\\newcommand{\\", {}, 0
    while True:
        start = src.find(head, pos)
        if start < 0:
            return out
        i = start + len(head)
        name = ""
        while i < len(src) and (src[i].isalnum() or src[i] == "_"):
            name += src[i]
            i += 1
        if i >= len(src) or src[i] != "}" or not src[i + 1:i + 2] == "{":
            pos = start + len(head)
            continue
        i += 2                                   # step over  }{
        depth, buf = 1, []
        while i < len(src) and depth:
            ch = src[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if not depth:
                    break
            buf.append(ch)
            i += 1
        out[name] = _resolve_macros("".join(buf).strip())
        pos = i


_MONTHS_PT = ("janeiro", "fevereiro", "março", "abril", "maio", "junho",
              "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")


def _resolve_macros(value: str) -> str:
    r"""Turn LaTeX metadata into the literal string the cover will print.

    The renderer treats every text element as LITERAL and escapes it — which is right for an
    OCR reading, and fatal for a macro: \today reached the page as the visible characters
    "\{}today" on every integrated cover. A macro has to be resolved HERE, where we still
    know it is LaTeX, or dropped so it cannot print as garbage.
    """
    from datetime import date

    if "\\" not in value:
        return value
    d = date.today()
    value = value.replace("\\today", f"{d.day} de {_MONTHS_PT[d.month - 1]} de {d.year}")
    if "\\" not in value:
        return value
    # Anything still carrying a control sequence would print as literal backslash soup.
    out, i = [], 0
    while i < len(value):
        if value[i] == "\\":
            i += 1
            while i < len(value) and value[i].isalpha():
                i += 1
        else:
            out.append(value[i])
            i += 1
    return " ".join("".join(out).split())


def group_blocks(elements: list) -> list:
    """Group text elements that read as ONE block (a wrapped title, a stacked address).

    capa1's title arrives as two 30pt elements, "Título do Livro" and "Técnico"; ranking
    slots individually would make the second line a subtitle. Three measured conditions have
    to hold together — same size, adjacent baselines, shared left margin — because any one
    of them alone merges things that are visibly separate.

    Returns a list of blocks, each a list of element indices, ordered by the block's largest
    font size (descending) so that block 0 is the most prominent thing on the cover.
    """
    order = sorted(range(len(elements)),
                   key=lambda i: (-(elements[i].get("bbox_cm") or {}).get("y", 0),
                                  (elements[i].get("bbox_cm") or {}).get("x", 0)))
    blocks, cur = [], []
    for idx in order:
        if not cur:
            cur = [idx]
            continue
        a, b = elements[cur[-1]], elements[idx]
        sa = a.get("font_size_pt") or 0.0
        sb = b.get("font_size_pt") or 0.0
        ba, bb = a.get("bbox_cm") or {}, b.get("bbox_cm") or {}
        em_cm = (max(sa, sb) / 72.0) * 2.54
        same_size = sa > 0 and sb > 0 and abs(sa - sb) / max(sa, sb) <= _SAME_BLOCK_SIZE_TOL
        near_y = abs(ba.get("y", 0) - bb.get("y", 0)) <= _SAME_BLOCK_GAP_EM * em_cm
        same_x = abs(ba.get("x", 0) - bb.get("x", 0)) <= _SAME_BLOCK_X_TOL_CM
        if same_size and near_y and same_x:
            cur.append(idx)
        else:
            blocks.append(cur)
            cur = [idx]
    if cur:
        blocks.append(cur)
    blocks.sort(key=lambda blk: -max((elements[i].get("font_size_pt") or 0) for i in blk))
    return blocks


def map_fields(elements: list, meta: dict) -> dict:
    """Decide which metadata string each text element should carry.

    Returns {element_index: new_string}. Blocks beyond the field list are left OUT of the
    mapping entirely — the caller keeps their original text, which is what the user chose.
    A block of N lines consumes ONE field: the field's own words are re-wrapped across the
    lines so a two-line title slot still reads as a two-line title.

    Logo PLACEHOLDERS are not content slots and never receive a field: "Versatus (Logo)" on
    capa1 marks where the real mark belongs, and handing it \\BookSubtitle would both lose
    the mark and waste a field.
    """
    live = [i for i, e in enumerate(elements) if not is_logo_placeholder(e.get("text", ""))]
    sub = [elements[i] for i in live]
    out = {}
    for field, blk in zip(_FIELD_ORDER, group_blocks(sub)):
        value = (meta.get(field) or "").strip()
        if not value:
            continue
        for j, chunk in zip(blk, _wrap(value, len(blk))):
            # A short field in a tall block would otherwise blank out the spare lines and
            # punch holes in the composition. An unassigned line keeps what it already says,
            # which is the same rule the leftover blocks follow.
            if chunk:
                out[live[j]] = chunk
    return out


def is_logo_placeholder(text: str) -> bool:
    """Is this the "<Name> (Logo)" marker that the logo.mark edit writes?"""
    return text.strip().endswith("(Logo)")


def _wrap(text: str, n: int) -> list:
    """Split a string into n line-chunks on word boundaries, as evenly as the words allow."""
    words = text.split()
    if n <= 1 or len(words) <= 1:
        return [text] + [""] * (n - 1)
    per, lines, cur = max(1, round(len(words) / n)), [], []
    for w in words:
        cur.append(w)
        if len(cur) >= per and len(lines) < n - 1:
            lines.append(" ".join(cur))
            cur = []
    lines.append(" ".join(cur))
    while len(lines) < n:
        lines.append("")
    return lines[:n]


# ─── Logo placement ───────────────────────────────────────────────────────────

_LOGO_TARGET_W_FRAC = 0.28    # a cover logo reads at roughly a quarter of the page width
_LOGO_MARGIN_FRAC   = 0.06    # keep it off the trim edge
_LOGO_GRID          = (6, 8)  # zones scanned when the analysis has no measured bbox


def brand_logo(brand: str = "versatus", variant: str = "light") -> dict:
    """Locate a brand's TikZ logo and measure its natural extent.

    The .tikz files are generated from SVG by svg_to_tikz.py and define one macro that takes
    a shift coordinate, e.g. \\LogoVersatusDark{(0,0)}. Their drawing units are arbitrary, so
    the extent is read back out of the path coordinates rather than assumed — that is what
    lets the caller scale the mark to a measured slot.
    """
    tikz = ROOT / "brands" / brand / "logos" / f"logo_{variant}.tikz"
    if not tikz.exists():
        return {}
    src = tikz.read_text(encoding="utf-8")
    macro = ""
    head = "\\newcommand{\\"
    at = src.find(head)
    if at >= 0:
        i = at + len(head)
        while i < len(src) and (src[i].isalnum() or src[i] == "_"):
            macro += src[i]
            i += 1
    xs, ys = [], []
    for chunk in src.split("(")[1:]:
        end = chunk.find(")")
        if end < 0:
            continue
        parts = chunk[:end].split(",")
        if len(parts) != 2:
            continue
        try:
            xs.append(float(parts[0]))
            ys.append(float(parts[1]))
        except ValueError:
            continue
    if not xs or not macro:
        return {}
    return {"macro": macro, "path": tikz,
            "w": max(xs) - min(xs), "h": max(ys) - min(ys),
            "x0": min(xs), "y0": min(ys)}


def logo_slot(analysis: dict, image_path=None) -> dict:
    """Where the brand mark goes, in cm, on the replicated canvas.

    Prefers a bbox the pipeline actually measured — `analysis["logos"]`, which only exists
    where the VLM proposed a `logo.mark` (capa1, capa7, capa14). Everywhere else the cover
    carries no measured logo position at all, so we place it in the emptiest zone: the page
    is cut into a grid and each cell scored by how little the ORIGINAL image varies inside
    it, which finds flat background rather than artwork or type. `has_logo` is deliberately
    ignored — it is inert and wrong in both directions (True on capa3, which is pure op-art;
    False on capa12 and capa15, which have text).
    """
    W = analysis["canvas"]["width_cm"]
    H = analysis["canvas"]["height_cm"]
    target_w = W * _LOGO_TARGET_W_FRAC

    for lg in (analysis.get("logos") or []):
        b = lg.get("bbox_cm") or {}
        if b.get("w"):
            return {"x": b["x"], "y": b["y"], "w": b["w"],
                    "h": b.get("h", b["w"] * 0.34), "source": "medido"}

    # A "<Name> (Logo)" placeholder is itself a measured position — it is where the VLM
    # recognised a mark and the pipeline wrote a stand-in. That is exactly the slot.
    for el in (analysis.get("text_elements") or []):
        if is_logo_placeholder(el.get("text", "")):
            b = el.get("bbox_cm") or {}
            if b.get("w"):
                return {"x": b["x"], "y": b["y"], "w": b["w"],
                        "h": b.get("h", b["w"] * 0.34), "source": "placeholder"}

    margin = min(W, H) * _LOGO_MARGIN_FRAC
    best = None
    try:
        import numpy as np              # noqa: PLC0415
        from PIL import Image           # noqa: PLC0415
        arr = np.asarray(Image.open(image_path).convert("RGB")).astype(float)
        h_px, w_px = arr.shape[:2]
        cols, rows = _LOGO_GRID
        for r in range(rows):
            for c in range(cols):
                x0, x1 = int(c * w_px / cols), int((c + 1) * w_px / cols)
                y0, y1 = int(r * h_px / rows), int((r + 1) * h_px / rows)
                cell = arr[y0:y1, x0:x1]
                if cell.size == 0:
                    continue
                busy = float(cell.reshape(-1, 3).std(axis=0).mean())
                x_cm = x0 / w_px * W
                y_cm = (h_px - y1) / h_px * H          # TikZ y grows upward
                if x_cm < margin or x_cm + target_w > W - margin or y_cm < margin:
                    continue
                # Flat in the ORIGINAL is not the same as free in OURS: the poster's calm
                # top band is exactly where our title lands. Any cell a text box touches is
                # disqualified, or the mark ends up printed through the type.
                if _hits_text(analysis, x_cm, y_cm, target_w, target_w * 0.34):
                    continue
                if best is None or busy < best[0]:
                    best = (busy, x_cm, y_cm)
    except Exception:
        best = None

    if best is None:
        return {"x": margin, "y": margin, "w": target_w,
                "h": target_w * 0.34, "source": "canto padrao"}
    _, x_cm, y_cm = best
    return {"x": round(x_cm, 2), "y": round(y_cm, 2), "w": round(target_w, 2),
            "h": round(target_w * 0.34, 2), "source": "zona mais vazia"}


_MIN_CONTRAST = 60.0   # luminance distance below which type stops being readable
_BG_SAMPLES   = 16     # points probed across a line to find where the ground changes
_BG_SPLIT_MIN = 80.0   # luminance step that counts as a real edge, not a shade


def _ensure_contrast(analysis: dict, image_path=None) -> None:
    """Recolour a line only when its own colour would make it unreadable where it now sits.

    Our strings are longer than the poster's, so a slot that sat entirely on yellow can end
    up crossing the black shape — capa19's title inherits #2B2A25 from "theshining" and half
    of it disappears. The colour is judged against the WORST background the line touches, not
    the average: a mid-grey can beat the mean and still vanish at both ends.

    A line that still reads is left exactly as measured. This is a readability floor, not a
    restyling — the poster's palette is what the user asked to keep.
    """
    def lum_hex(h):
        h = (h or "").lstrip("#")
        try:
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        except Exception:
            return None
        return 0.299 * r + 0.587 * g + 0.114 * b

    # The background is taken from the REGIONS, not from the source image: the image still
    # carries the poster's own ink, so sampling it reads the old type as "background" and
    # flips colours that were perfectly readable. The regions are the paint layer, which is
    # what will actually sit behind our text.
    regions = [r for r in (analysis.get("regions") or []) if r.get("bbox_cm")]
    page_bg = None
    for c in sorted((analysis.get("colors") or []),
                    key=lambda c: -(c.get("coverage") or 0)):
        page_bg = lum_hex(c.get("hex"))
        if page_bg is not None:
            break
    if page_bg is None:
        page_bg = 255.0

    palette = []
    for c in (analysis.get("colors") or []):
        L = lum_hex(c.get("hex"))
        if L is not None:
            palette.append((c["hex"], L))
    palette += [("#FFFFFF", 255.0), ("#000000", 0.0)]

    def bg_at(px, py):
        top = page_bg
        for r in regions:                       # later regions paint over earlier ones
            rb = r["bbox_cm"]
            if (rb["x"] <= px <= rb["x"] + rb["w"]
                    and rb["y"] <= py <= rb["y"] + rb["h"]):
                L = lum_hex(r.get("color_hex"))
                if L is not None:
                    top = L
        return top

    def pick(lo, hi):
        return max(palette, key=lambda p: min(abs(p[1] - lo), abs(p[1] - hi)))[0]

    out = []
    for el in (analysis.get("text_elements") or []):
        b = el.get("bbox_cm") or {}
        if not b.get("w"):
            out.append(el)
            continue
        py = b["y"] + b.get("h", 0.2) * 0.5
        seen = [bg_at(b["x"] + b["w"] * (i + 0.5) / _BG_SAMPLES, py)
                for i in range(_BG_SAMPLES)]

        # A line that crosses a hard edge cannot be served by ONE colour: the best single
        # choice for black-and-yellow is a mid olive that reads poorly on both. Split it
        # where the ground actually changes and let each part contrast with its own.
        jump, at = 0.0, None
        for i in range(1, len(seen)):
            d = abs(seen[i] - seen[i - 1])
            if d > jump:
                jump, at = d, i
        # SPLITTING A LINE IN TWO IS OFF, and the reason is measurement, not design.
        # Positioning the second half requires knowing the exact width of the first, and the
        # only width we have is ~0.52em per character — an average that is several percent
        # wrong on narrow glyphs. At caption sizes that error hides in a word space; on
        # capa19's 76pt title it opened a visible gulf inside the word ("Título    do").
        # _prefer_legible_wrap now handles the underlying problem — type on mixed ground —
        # by moving the type to calm ground instead, which needs no width estimate at all.
        # Re-enable this only with real font metrics measured in LuaLaTeX.
        if False and jump >= _BG_SPLIT_MIN and at is not None:
            frac = at / len(seen)
            n = max(1, min(len(el["text"]) - 1, round(frac * len(el["text"]))))
            # Prefer to change colour at a SPACE. The per-character width estimate is a few
            # percent off on narrow glyphs, so a mid-word boundary leaves a visible sliver
            # inside the word; the same error inside a word gap reads as ordinary spacing.
            near = [i for i, c in enumerate(el["text"]) if c == " "
                    and abs(i - n) <= max(2, 0.25 * len(el["text"]))]
            if near:
                n = min(near, key=lambda i: abs(i - n))
            # Position the halves by CHARACTER count, not by the sampling fraction: the two
            # disagree by a fraction of a glyph and the parts drift apart, leaving a visible
            # gap mid-word. Splitting the box in the same proportion the text was split makes
            # them butt exactly.
            cut = _text_w_cm(el["text"][:n], el.get("font_size_pt") or 0.0, el)
            left, right = seen[:at], seen[at:]
            for text, x, w, side in (
                (el["text"][:n], b["x"], cut, left),
                (el["text"][n:], b["x"] + cut, b["w"] - cut, right),
            ):
                if not text:
                    continue
                part = dict(el)
                part["text"] = text
                part["bbox_cm"] = {**b, "x": round(x, 3), "w": round(w, 3)}
                cl = lum_hex(part.get("color_hex"))
                if cl is None or min(abs(cl - min(side)), abs(cl - max(side))) < _MIN_CONTRAST:
                    part["color_hex"] = pick(min(side), max(side))
                out.append(part)
            continue

        lo, hi = min(seen), max(seen)
        cur_l = lum_hex(el.get("color_hex"))
        if cur_l is not None and min(abs(cur_l - lo), abs(cur_l - hi)) < _MIN_CONTRAST:
            el["color_hex"] = pick(lo, hi)
        out.append(el)
    analysis["text_elements"] = out


_LOGO_TEXT_GAP_CM = 0.3     # breathing room demanded between the mark and any type


def _hits_text(analysis: dict, x: float, y: float, w: float, h: float) -> bool:
    """Would a mark of this size at this spot land on a text box (plus a little air)?"""
    g = _LOGO_TEXT_GAP_CM
    for el in (analysis.get("text_elements") or []):
        b = el.get("bbox_cm") or {}
        if not b:
            continue
        if (x < b.get("x", 0) + b.get("w", 0) + g and x + w + g > b.get("x", 0)
                and y < b.get("y", 0) + b.get("h", 0) + g and y + h + g > b.get("y", 0)):
            return True
    return False


def logo_variant_for(slot: dict, analysis: dict, image_path=None) -> str:
    """Pick the dark-ground or light-ground cut by measuring what is actually behind it."""
    try:
        import numpy as np              # noqa: PLC0415
        from PIL import Image           # noqa: PLC0415
        W = analysis["canvas"]["width_cm"]
        H = analysis["canvas"]["height_cm"]
        arr = np.asarray(Image.open(image_path).convert("RGB")).astype(float)
        h_px, w_px = arr.shape[:2]
        x0 = int(slot["x"] / W * w_px)
        x1 = int((slot["x"] + slot["w"]) / W * w_px)
        y1 = int((H - slot["y"]) / H * h_px)
        y0 = int(y1 - slot["h"] / H * h_px)
        patch = arr[max(0, y0):min(h_px, y1), max(0, x0):min(w_px, x1)]
        if patch.size:
            lum = float((0.299 * patch[..., 0] + 0.587 * patch[..., 1]
                         + 0.114 * patch[..., 2]).mean())
            return "dark" if lum < 128 else "light"
    except Exception:
        pass
    return "light"


def logo_tikz(slot: dict, logo: dict) -> str:
    """One TikZ scope that drops the brand macro into the measured slot, to scale."""
    if not logo:
        return ""
    scale = slot["w"] / logo["w"] if logo.get("w") else 1.0
    x = slot["x"] - logo["x0"] * scale
    y = slot["y"] - logo["y0"] * scale
    return (f"  % marca da casa — slot {slot.get('source', '')}\n"
            f"  \\begin{{scope}}[shift={{({x:.3f},{y:.3f})}}, scale={scale:.4f}]\n"
            f"    \\{logo['macro']}{{(0,0)}}\n"
            f"  \\end{{scope}}\n")


# ─── Integration ──────────────────────────────────────────────────────────────

def integrate(analysis: dict, meta: dict, image_path=None, brand: str = "versatus") -> dict:
    """Return a COPY of the analysis carrying our content instead of the poster's.

    Geometry is untouched: every bbox, font size, weight, rotation and colour survives. Only
    the strings change, and only in the slots the priority mapping claims — the rest keep
    what the OCR read, which is the behaviour the user picked.
    """
    out = json.loads(json.dumps(analysis))
    els = out.get("text_elements") or []
    mapping = map_fields(els, meta)
    W = out["canvas"]["width_cm"]
    rebuilt = []
    for i, el in enumerate(els):
        if i in mapping:
            rebuilt.extend(_fit_to_slot(el, mapping[i], W, src=i))
        else:
            rebuilt.append(el)
    rebuilt = _resolve_collisions(rebuilt, els, mapping, W)
    # Keep the SLOT-indexed field map and the untouched originals: the legibility pass below
    # may need to lay a slot out again from scratch, and by then `els` has been rewritten.
    field_map, source_els = dict(mapping), els
    out["text_elements"] = els = rebuilt
    mapping = {i: e["text"] for i, e in enumerate(els) if e.get("_filled")}

    kept = [i for i in range(len(els))
            if i not in mapping and not is_logo_placeholder(els[i].get("text", ""))]
    out["integration"] = {
        "brand": brand,
        "fields_placed": {str(i): v for i, v in sorted(mapping.items())},
        "slots_kept_original": kept,
    }
    slot = logo_slot(out, image_path)
    # The stand-in text goes away: the real mark is about to be drawn in its place. This has
    # to happen BEFORE the contrast pass, which rewrites the element list wholesale — reading
    # `els` again afterwards would silently throw the recolouring away.
    out["text_elements"] = [e for e in els if not is_logo_placeholder(e.get("text", ""))]
    _ensure_contrast(out, image_path)
    _prefer_legible_wrap(out, source_els, field_map, W)
    for e in out["text_elements"]:      # scratch keys never reach the analysis on disk
        e.pop("_role", None)
        e.pop("_filled", None)
        e.pop("_lines", None)
        e.pop("_src", None)
    variant = logo_variant_for(slot, out, image_path)
    logo = brand_logo(brand, variant)
    out["integration"]["logo"] = {"slot": slot, "variant": variant,
                                  "macro": logo.get("macro"), "found": bool(logo)}
    return out


_CHAR_EM      = 0.52    # same width estimate the renderer's overflow cap uses
_PT_PER_CM    = 72.0 / 2.54
_HSCALE       = 0.89    # tikz_generator's default \scalebox on every text node


def _text_w_cm(text: str, pt: float, el: dict) -> float:
    """Width the renderer will actually produce for this string.

    The horizontal \\scalebox the generator puts on every text node has to be in here. Leaving
    it out makes every box 12% too wide, and since the contrast split positions the second
    half at the end of the first, that error becomes a visible gap mid-word on capa19 and
    pushes capa8's title off the right edge.
    """
    hs = el.get("hscale") or _HSCALE
    return len(text) * pt * _CHAR_EM / _PT_PER_CM * hs
_LEADING      = 1.18    # line pitch as a multiple of the font size
_RIGHT_MARGIN = 0.4     # cm of air kept at the trim edge
_MAX_LINES     = 3      # a title may break, but it must not become a column
_COLLIDE_STEPS  = 24   # shrink attempts before we accept the overlap and move on
_COLLIDE_SHRINK = 0.10 # how much a colliding box gives up per attempt
_MIN_PT         = 6.0  # below this the type is no longer worth saving
_STACK_GAP_CM   = 0.12 # air left between two stacked captions
_STACK_MAX_CM   = 4.0  # a caption may drop this far to clear its neighbour, no more
_MIN_SIZE_FRAC = 0.55   # how much of the measured size a slot must keep


def _fit_to_slot(el: dict, value: str, canvas_w: float, src: int = -1) -> list:
    """Set `value` in this slot WITHOUT surrendering the slot's type size.

    Our strings are longer than the poster's: capa19's title box holds "theshining" (10
    chars) and has to take "Título do Livro Técnico" (23). Left alone, the renderer's
    overflow cap shrinks that title from 103.8pt to 45.1pt — it fits, and the cover loses
    the typographic dominance that IS the Swiss design. So we do what a designer does and
    break the line instead, keeping the measured size, weight and left margin and stacking
    the extra lines downward on the slot's own leading.
    """
    avail_pt = max(2.0, canvas_w - (el.get("bbox_cm") or {}).get("x", 0.0)
                   - _RIGHT_MARGIN) * _PT_PER_CM
    nominal = el.get("font_size_pt") or 0.0
    if nominal <= 0 or not value.strip():
        part = dict(el)
        part["text"] = value
        part["_filled"] = True
        part["_lines"] = 1
        part["_src"] = src
        return [part]

    # Line count and type size are chosen TOGETHER. One line would shrink capa19's title to
    # 29% of its measured size; four lines keep the size but turn a title into a column. We
    # take the fewest lines whose required size still holds _MIN_SIZE_FRAC of the original,
    # so the title stays dominant without stacking into a tower.
    hs = el.get("hscale") or _HSCALE
    best_lines, best_pt = [value], nominal
    for n in range(1, _MAX_LINES + 1):
        lines = [ln for ln in _wrap(value, n) if ln] or [value]
        # Size from the LONGEST line that actually came out, not from len/n. _wrap breaks on
        # words, so the real lines are uneven: "Livro Técnico" is 13 characters where len/n
        # predicted 12, and that one character ran capa19's title off the page.
        longest = max(len(ln) for ln in lines)
        fit = min(nominal, avail_pt / (longest * _CHAR_EM * hs))
        best_lines, best_pt = lines, fit
        if fit >= nominal * _MIN_SIZE_FRAC:
            break

    lines = best_lines
    step = (best_pt * _LEADING) / _PT_PER_CM
    out = []
    for k, line in enumerate(lines):
        part = dict(el)
        part["text"] = line
        part["_filled"] = True
        part["_lines"] = len(lines)
        part["_src"] = src
        part["font_size_pt"] = round(best_pt, 1)
        b = dict(el.get("bbox_cm") or {})
        b["y"] = round(b.get("y", 0.0) - k * step, 3)
        # The box has to describe OUR string, not the poster's. Keeping the measured width
        # makes the bbox lie — "Autor / Organização" inherited 4.97cm while it renders about
        # 14cm — and everything that reasons about the layout downstream (logo placement,
        # overlap) then trusts a number that is wrong by 3x.
        b["w"] = round(_text_w_cm(line, best_pt, el), 3)
        b["h"] = round(best_pt / _PT_PER_CM, 3)
        part["bbox_cm"] = b
        if "baseline_y_cm" in part:
            part["baseline_y_cm"] = round(part["baseline_y_cm"] - k * step, 3)
        out.append(part)
    return out


_LEGIBLE_FLOOR = 90.0   # below this the type is fighting its ground and has to give


def _prefer_legible_wrap(analysis: dict, original: list, mapping: dict,
                         canvas_w: float) -> None:
    """Trade type size for readability when a wrapped line lands on busy artwork.

    Breaking a long title into lines keeps its size, but the extra lines extend DOWNWARD out
    of the calm band the poster reserved for type. On capa16 the original title "vision" sat
    on flat ground at the bottom left; our two-line title pushes its second line onto the
    diamond lattice, where it measures 49 on the legibility scale against 119-212 for every
    other element on the page — the words are simply not readable.

    So the line count is re-chosen with legibility in the objective, not just size: fewer
    lines at a smaller size, if that is what keeps the words on ground they can be read on.
    """
    global _MAX_LINES
    by_src = {}
    for e in analysis.get("text_elements") or []:
        if e.get("_src") is not None:
            by_src.setdefault(e["_src"], []).append(e)

    for src, group in by_src.items():
        if len(group) < 2 or src not in mapping:
            continue
        worst = min(legibility(analysis, e) for e in group)
        if worst >= _LEGIBLE_FLOOR:
            continue
        keep, _MAX_LINES = _MAX_LINES, len(group) - 1
        try:
            candidate = _fit_to_slot(original[src], mapping[src], canvas_w, src=src)
        finally:
            _MAX_LINES = keep
        for part in candidate:                      # inherit the colour already resolved
            part["color_hex"] = group[0].get("color_hex", part.get("color_hex"))
        if min(legibility(analysis, e) for e in candidate) <= worst:
            continue                                # fewer lines did not actually help
        rest = [e for e in analysis["text_elements"] if e.get("_src") != src]
        analysis["text_elements"] = sorted(
            rest + candidate,
            key=lambda e: (-(e.get("bbox_cm") or {}).get("y", 0),
                           (e.get("bbox_cm") or {}).get("x", 0)))


def _boxes_hit(a: dict, b: dict) -> bool:
    """Do two text boxes overlap? Pure geometry, no allowance — touching is fine."""
    ba, bb = a.get("bbox_cm") or {}, b.get("bbox_cm") or {}
    if not (ba.get("w") and bb.get("w")):
        return False
    return (ba["x"] < bb["x"] + bb["w"] and ba["x"] + ba["w"] > bb["x"]
            and ba["y"] < bb["y"] + bb["h"] and ba["y"] + ba["h"] > bb["y"])


def _resolve_collisions(rebuilt: list, original: list, mapping: dict, canvas_w: float) -> list:
    """Undo a line break that made a slot run into its neighbour.

    Wrapping stacks the extra lines DOWNWARD from the slot, which is fine on a sparse cover
    and not fine on a dense one: capa14 has 17 text elements and capa15 ten, and there the
    second and third lines land on top of the block below. Both were unreadable.

    The slot is re-set on a single line — smaller type, but type that can be read. Only slots
    WE filled are touched; a collision between two of the poster's own boxes was there in the
    original and is not ours to reflow.
    """
    for _ in range(_COLLIDE_STEPS):
        victim = partner = None
        for i, a in enumerate(rebuilt):
            for j, b in enumerate(rebuilt):
                if i >= j or not _boxes_hit(a, b):
                    continue
                # Only a box we filled may be reflowed, and between two of ours the SMALLER
                # one yields — shrinking the title to save a caption inverts the hierarchy.
                cand = [k for k in (i, j) if rebuilt[k].get("_filled")]
                if cand:
                    victim = min(cand, key=lambda k: rebuilt[k].get("font_size_pt") or 0)
                    partner = j if victim == i else i
                    break
            if victim is not None:
                break
        if victim is None:
            return rebuilt

        el = rebuilt[victim]
        b = el.get("bbox_cm") or {}
        other = rebuilt[partner]
        ob = other.get("bbox_cm") or {}

        # STACK before shrinking. Our strings are far wider than the poster's little labels,
        # so on a dense cover half a dozen of them overlap sideways at once; shaving 10% off
        # each in turn never converges and just leaves a pile of tiny type. Dropping the
        # smaller one below its neighbour is what actually separates them, and it is what a
        # designer does with a column of captions.
        drop = (ob.get("y", 0) - b.get("y", 0)) + (b.get("h", 0) + _STACK_GAP_CM)
        if 0 < drop <= _STACK_MAX_CM:
            snapshot = json.loads(json.dumps(el))
            b["y"] = round(b.get("y", 0) - drop, 3)
            if "baseline_y_cm" in el:
                el["baseline_y_cm"] = round(el["baseline_y_cm"] - drop, 3)
            fits = b["y"] >= 0 and not any(
                _boxes_hit(el, o) for k, o in enumerate(rebuilt) if k != victim)
            if fits:
                continue
            el.clear()
            el.update(snapshot)
            b = el["bbox_cm"]

        pt = (el.get("font_size_pt") or 0) * (1 - _COLLIDE_SHRINK)
        if pt < _MIN_PT:
            return rebuilt
        el["font_size_pt"] = round(pt, 1)
        b["w"] = round(_text_w_cm(el.get("text", ""), pt, el), 3)
        b["h"] = round(pt / _PT_PER_CM, 3)
    return rebuilt


_TEX_SPECIAL = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
                "_": r"\_", "{": r"\{", "}": r"\}"}


def tex_escape(text: str) -> str:
    r"""Make a metadata string safe inside a TikZ node.

    Book titles are user data and will eventually contain an ampersand or a percent. Macros
    are left alone on purpose: \today is a legitimate metadata value, so a leading backslash
    is treated as intent rather than escaped into visible text.
    """
    if "\\" in text:
        return text
    return "".join(_TEX_SPECIAL.get(c, c) for c in text)


def build(n, brand: str = "versatus", tag: str = "integrated") -> dict:
    """Render cover `n` with our content in it. Returns the paths and the placement report."""
    import importlib.util
    import shutil

    def _load(name):
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "automation" / "scripts" / f"{name}.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    rc, tg = _load("replicate_cover"), _load("tikz_generator")

    d = ROOT / "automation" / "output" / "replicated" / f"capa_teste{n}"
    img = ROOT / "capas_teste" / f"capa_teste{n}.png"
    analysis = json.loads((d / "analysis.json").read_text(encoding="utf-8"))

    # NOTE: no escaping here on purpose — tikz_generator._escape_latex already escapes every
    # text node. Doing it twice turned "&" into a literal \textbackslash{}& on the page.
    # Compose on the artwork instead of inheriting the poster's text slots. The slot path
    # remains in `integrate()` for reference, but it scattered our words across positions
    # chosen for other words, and the pages read as debris.
    merged = compose(analysis, parse_metadata(), str(d / "render.png"), brand)
    return emit(merged, d, tag=tag, brand=brand, n=n)


def emit(merged: dict, d: Path, tag: str = "integrated", brand: str = "versatus",
         n=None) -> dict:
    """Write tikz + logo, compile, render. Split out so a refinement pass can re-render."""
    import importlib.util
    import shutil

    def _load(name):
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "automation" / "scripts" / f"{name}.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    rc, tg = _load("replicate_cover"), _load("tikz_generator")
    W = merged["canvas"]["width_cm"]
    H = merged["canvas"]["height_cm"]
    tikz = d / f"{tag}.tikz"
    tg.generate(merged, tikz)

    info = merged["integration"]
    logo = brand_logo(brand, info["logo"]["variant"])
    body = tikz.read_text(encoding="utf-8")
    if logo:
        # Ship the brand file next to the cover so the output stands on its own.
        local = d / logo["path"].name
        shutil.copyfile(logo["path"], local)
        body = (f"\\input{{{local.name}}}%\n" + body).replace(
            "  \\end{tikzpicture}%",
            logo_tikz(info["logo"]["slot"], logo) + "  \\end{tikzpicture}%", 1)
        tikz.write_text(body, encoding="utf-8")

    tex, pdf, png = d / f"{tag}.tex", d / f"{tag}.pdf", d / f"{tag}.png"
    rc._write_tex_wrapper(tex, tikz, merged, W, H)
    ok, err = rc._compile_lualatex(tex, pdf)
    if not ok:
        return {"n": n, "ok": False, "error": err[:300], "info": info}
    rc._render_pdf(pdf, png, 150)
    (d / f"{tag}_analysis.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"n": n, "ok": True, "pdf": pdf, "png": png, "info": info, "analysis": merged}


def build_refined(n, brand: str = "versatus", rounds: int = 1,
                  refresh: bool = False) -> dict:
    """Integrate, then let the VLM criticise the finished page and fix the typography.

    The proposals are cached per cover, so a re-run costs nothing in API. Pass refresh=True
    to actually call Gemini again.
    """
    d = ROOT / "automation" / "output" / "replicated" / f"capa_teste{n}"
    cache = d / "refine_edits.json"

    res = build(n, brand=brand, tag="integrated")
    if not res["ok"]:
        return res
    merged = res["analysis"]

    for rnd in range(1, rounds + 1):
        edits = None
        if cache.exists() and not refresh:
            try:
                edits = json.loads(cache.read_text(encoding="utf-8")).get(str(rnd))
            except Exception:
                edits = None
        if edits is None:
            edits = propose_refinements(merged, res["png"])
            store = {}
            if cache.exists():
                try:
                    store = json.loads(cache.read_text(encoding="utf-8"))
                except Exception:
                    store = {}
            store[str(rnd)] = edits
            cache.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")

        kept, dropped = apply_refinements(merged, edits or [])
        print(f"    rodada {rnd}: {len(kept)} aceitos, {len(dropped)} rejeitados")
        for ed, why in dropped[:4]:
            print(f"       x {ed.get('op')} id={ed.get('id')}: {why}")
        if not kept:
            break
        res = emit(merged, d, tag="integrated", brand=brand, n=n)
        if not res["ok"]:
            return res
        merged = res["analysis"]

    return res



# ─── Composição (substitui o preenchimento de slots) ──────────────────────────

_MARGIN_FRAC   = 0.085   # page margin as a fraction of the SHORT side
_CALM_STD      = 26.0    # a band is calm when its colour spread is under this
_TITLE_FILL    = 0.94    # the title should fill this much of the column
_SUB_RATIO     = 0.30    # subtitle size relative to the title
_META_RATIO    = 0.115   # the small block, relative to the title
_META_MIN_PT   = 9.5
_META_LEAD     = 1.45    # leading inside the small block, in multiples of its size
_LOGO_W_FRAC   = 0.26
_TITLE_MIN_PT  = 34.0    # a cover title never goes below this
_TITLE_MAX_PT  = 78.0    # ...nor above, or two lines stop fitting the page


def _row_calm(image_path, W, H, rows=120):
    """Colour spread of the ARTWORK in each horizontal slice, top row first.

    Measured on the replica we actually drew, not on the source photo, because that is what
    the type will sit on. A band with a low spread is flat colour; a high spread is pattern,
    a diagonal, or an edge — the places type must not land.
    """
    import numpy as np
    from PIL import Image

    arr = np.asarray(Image.open(image_path).convert("RGB")).astype(float)
    h_px = arr.shape[0]
    out = []
    for r in range(rows):
        y0, y1 = int(r * h_px / rows), int((r + 1) * h_px / rows)
        band = arr[y0:y1].reshape(-1, 3)
        out.append(float(band.std(axis=0).mean()) if len(band) else 999.0)
    return out


def _calm_runs(calm, H, rows=120):
    """Contiguous calm bands as (y_bottom_cm, y_top_cm, height_cm, mean_spread)."""
    runs, start = [], None
    for r, v in enumerate(calm + [999.0]):
        if v <= _CALM_STD and start is None:
            start = r
        elif v > _CALM_STD and start is not None:
            top_cm = H * (1 - start / rows)
            bot_cm = H * (1 - r / rows)
            mean = sum(calm[start:r]) / max(1, r - start)
            runs.append((bot_cm, top_cm, top_cm - bot_cm, mean))
            start = None
    return sorted(runs, key=lambda t: -t[2])


def _fit_size(text: str, column_cm: float, el_proto: dict, lines: int = 1) -> float:
    """Largest point size at which `text` fills the column in `lines` lines."""
    per_line = max(1, -(-len(text) // lines))
    return column_cm * _PT_PER_CM / (per_line * _CHAR_EM * (el_proto.get("hscale") or _HSCALE))


def _ink_for(analysis: dict, x, y, w, h) -> str:
    """The palette colour with the most contrast against the ground under this box."""
    def lum_hex(hx):
        hx = (hx or "").lstrip("#")
        try:
            r, g, b = (int(hx[i:i + 2], 16) for i in (0, 2, 4))
        except Exception:
            return None
        return 0.299 * r + 0.587 * g + 0.114 * b

    regions = [r for r in (analysis.get("regions") or []) if r.get("bbox_cm")]
    page_bg = next((lum_hex(c.get("hex")) for c in
                    sorted((analysis.get("colors") or []), key=lambda c: -(c.get("coverage") or 0))
                    if lum_hex(c.get("hex")) is not None), 255.0)
    grounds = []
    for i in range(9):
        for j in range(3):
            px, py = x + w * (i + 0.5) / 9, y + h * (j + 0.5) / 3
            top = page_bg
            for r in regions:
                rb = r["bbox_cm"]
                if rb["x"] <= px <= rb["x"] + rb["w"] and rb["y"] <= py <= rb["y"] + rb["h"]:
                    L = lum_hex(r.get("color_hex"))
                    if L is not None:
                        top = L
            grounds.append(top)
    # Follow the ground the type MOSTLY sits on, and use the SAME definition of "the ground"
    # that the renderer will be told about. Choosing the ink against the median of samples
    # while declaring the dominant region as the background let the two disagree: capa11's
    # title came out white on a ground the guard called white, and vanished.
    gh = _ground_under(analysis, x, y, w, h).lstrip("#")
    try:
        dominant = (0.299 * int(gh[0:2], 16) + 0.587 * int(gh[2:4], 16)
                    + 0.114 * int(gh[4:6], 16))
    except Exception:
        grounds.sort()
        dominant = grounds[len(grounds) // 2]
    cands = [(c["hex"], lum_hex(c["hex"])) for c in (analysis.get("colors") or [])
             if lum_hex(c.get("hex")) is not None]
    cands += [("#FFFFFF", 255.0), ("#111111", 17.0)]
    return max(cands, key=lambda p: abs(p[1] - dominant))[0]



_PANEL_MIN_COVERAGE = 0.04   # a panel colour has to be one the design actually uses




def _ground_under(analysis: dict, x, y, w, h) -> str:
    """The colour that covers most of this box — the ground the type will be read against."""
    best, best_area = None, 0.0
    for r in (analysis.get("regions") or []):
        rb = r.get("bbox_cm") or {}
        if not rb:
            continue
        ov = (max(0.0, min(rb["x"] + rb["w"], x + w) - max(rb["x"], x))
              * max(0.0, min(rb["y"] + rb["h"], y + h) - max(rb["y"], y)))
        if ov > best_area:
            best, best_area = r.get("color_hex"), ov
    if best:
        return best
    cols = sorted((analysis.get("colors") or []), key=lambda c: -(c.get("coverage") or 0))
    return cols[0]["hex"] if cols else "#FFFFFF"


def _register_colour(analysis: dict, hex_: str) -> str:
    """Make sure a colour we chose actually exists in the palette we hand the renderer.

    The generator resolves a text colour by looking it up in the palette; when it misses it
    falls back to "the palette entry furthest from the PAGE background". On a light page that
    is black — so the white title we chose for a black panel came out black on black and
    vanished. Registering the colour makes the renderer use exactly what was decided.
    """
    h = "#" + hex_.lstrip("#").upper()
    cols = analysis.setdefault("colors", [])
    if not any((c.get("hex") or "").upper() == h for c in cols):
        cols.append({"hex": h, "coverage": 0.0, "source": "compose"})
    return h


def _panel_colour(analysis: dict, panel: dict) -> str:
    """Choose the panel's colour from the design's own significant colours.

    Contrast alone is not enough: on capa19 the most contrasting entry was an olive that
    covers a fraction of a percent of the poster — a colour nobody would say the design is
    made of. Restricting the choice to colours with real coverage keeps the panel looking
    like part of the same object, and among those we still take the one that separates best
    from the artwork it sits on.
    """
    def lum_hex(hx):
        hx = (hx or "").lstrip("#")
        try:
            r, g, b = (int(hx[i:i + 2], 16) for i in (0, 2, 4))
        except Exception:
            return None
        return 0.299 * r + 0.587 * g + 0.114 * b

    cands = [(c["hex"], lum_hex(c.get("hex")))
             for c in (analysis.get("colors") or [])
             if (c.get("coverage") or 0) >= _PANEL_MIN_COVERAGE and lum_hex(c.get("hex")) is not None]
    if not cands:
        return _ink_for(analysis, panel["x"], panel["y"], panel["w"], panel["h"])

    # what the panel covers, by area
    covered = []
    for r in (analysis.get("regions") or []):
        rb = r.get("bbox_cm") or {}
        if not rb:
            continue
        ov = (max(0.0, min(rb["x"] + rb["w"], panel["x"] + panel["w"]) - max(rb["x"], panel["x"]))
              * max(0.0, min(rb["y"] + rb["h"], panel["y"] + panel["h"]) - max(rb["y"], panel["y"])))
        L = lum_hex(r.get("color_hex"))
        if ov > 0 and L is not None:
            covered.append((ov, L))
    if not covered:
        covered = [(1.0, lum_hex(cands[0][0]) or 128.0)]
    total = sum(o for o, _ in covered) or 1.0
    mean_under = sum(o * L for o, L in covered) / total

    # separate from the art, and leave room for type to contrast against the panel itself
    return max(cands, key=lambda c: abs(c[1] - mean_under) + min(c[1], 255 - c[1]) * 0.35)[0]



def compose(analysis: dict, meta: dict, render_path, brand: str = "versatus") -> dict:
    """Artwork as background, Versatus content on top, nothing of the poster's words left.

    The poster's text boxes become empty zones and our fields are set into them, shrunk to
    fit. The artwork is never covered and never moved.
    """
    out = json.loads(json.dumps(analysis))
    W = out["canvas"]["width_cm"]
    H = out["canvas"]["height_cm"]
    margin = min(W, H) * _MARGIN_FRAC

    originals = [e for e in (out.get("text_elements") or [])
                 if not is_logo_placeholder(e.get("text", ""))]
    _drop_traced_type(out, originals)
    proto = {k: originals[0][k] for k in ("font_family", "latex_cmd", "latex_pkg")
             if originals and k in originals[0]} if originals else {}

    # The poster's own type is not ours to keep: this version carries Versatus content only.
    out["text_elements"] = []

    fields = [("BookTitle", "bold"), ("BookSubtitle", "regular"), ("BookAuthor", "bold"),
              ("BookSeries", "regular"), ("BookDescription", "regular"),
              ("BookVersion", "regular"), ("BookDate", "regular")]
    values = [(meta.get(k, "").strip(), w) for k, w in fields]
    values = [(v, w) for v, w in values if v]

    zones = _text_zones(originals, W, H, margin)
    placed = []

    if not zones:
        # A cover with no type of its own (capa3 is pure op-art). Set a quiet block on the
        # calmest ground rather than inventing a position.
        zones = _fallback_zone(out, render_path, W, H, margin)

    # Title and subtitle take a zone each; every remaining field stacks inside ONE zone.
    # Giving each field its own zone scattered the imprint across the page — author bottom
    # left, version centre, date right — because the poster's little labels sit apart.
    groups = []
    for i, (value, weight) in enumerate(values[:2]):
        groups.append(([value], weight))
    rest = [v for v, _ in values[2:]]
    if rest:
        groups.append((rest, "regular"))

    for i, (chunk, weight) in enumerate(groups):
        if i >= len(zones):
            break
        z = zones[i]
        value = chunk[0] if len(chunk) == 1 else None
        if value is None:
            pt, lines = _stack_in_zone(chunk, z, proto)
        else:
            lines_wanted = z["lines"] if i == 0 else max(1, min(z["lines"], 2))
            zy = z["top"] - z["height"] * 0.5
            gx, gw = _single_ground_span(out, z, zy)
            z = {**z, "x": gx, "width": gw}
            pt, lines = _shrink_to_zone(value, z, proto, lines_wanted)
            if i == 0 and pt < _TITLE_FLOOR_PT:
                # The poster reserved this spot for a short label, so honouring its box
                # verbatim leaves our title at 11-15pt — no longer a title. Let it take the
                # widest FLAT run at this height and grow into it. Flat only: never pattern,
                # and the artwork is still not covered, only written across.
                fx, fw = _widest_flat_run(out, zy, W, margin)
                wide = {**z, "x": fx, "width": fw, "pt": _TITLE_GROWN_MAX,
                        "height": max(z["height"], _TITLE_GROWN_MAX / _PT_PER_CM * 2.4)}
                pt2, lines2 = _shrink_to_zone(value, wide, proto, min(2, lines_wanted + 1))
                if pt2 > pt:
                    z, pt, lines = wide, pt2, lines2
        step = pt * _LEADING / _PT_PER_CM
        block_h = len(lines) * step
        # Keep the block on the page. The fallback zone for artwork with no type of its own
        # reported a top near the foot, and the stack ran straight off the bottom edge —
        # capa3's whole imprint was set at negative y and simply never appeared.
        top = min(z["top"], H - margin * 0.5)
        if top - block_h < margin * 0.5:
            top = margin * 0.5 + block_h
        for k, ln in enumerate(lines):
            y = top - (k + 1) * step + step * 0.22
            ink = _register_colour(
                out, _ink_for(out, z["x"], y, _text_w_cm(ln, pt, proto), pt / _PT_PER_CM))
            placed.append({**proto, "text": ln, "font_size_pt": round(pt, 1),
                           "_role": ("title" if i == 0 else
                                     "sub" if i == 1 else "foot"),
                           "weight_hint": weight, "color_hex": ink,
                           "bg_hex": _ground_under(out, z["x"], y,
                                                   _text_w_cm(ln, pt, proto),
                                                   pt / _PT_PER_CM),
                           "bbox_cm": {"x": round(z["x"], 3), "y": round(y, 3),
                                       "w": round(_text_w_cm(ln, pt, proto), 3),
                                       "h": round(pt / _PT_PER_CM, 3)},
                           "baseline_y_cm": round(y, 3)})

    _clamp_to_page(placed, W, margin)
    _separate(placed, W, H, margin)
    _clamp_to_page(placed, W, margin)
    out["text_elements"] = placed

    slot = _mark_slot(out, analysis, placed, W, H, margin, render_path)
    # The user's own calls, cover by cover, applied last so nothing undoes them.
    _clear_under_type(out, placed)
    variant = logo_variant_for(slot, out, render_path)
    out["integration"] = {
        "brand": brand, "mode": "background+versatus",
        "fields_placed": {str(i): e["text"] for i, e in enumerate(placed)},
        "slots_kept_original": [],
        "logo": {"slot": slot, "variant": variant,
                 "macro": (brand_logo(brand, variant) or {}).get("macro"), "found": True},
    }
    return out




def _clamp_to_page(placed: list, W: float, margin: float) -> None:
    """Keep every line inside the page, with room for the first glyph's side bearing.

    The renderer anchors a node at the glyph ORIGIN and shifts left by the side bearing, so a
    box sitting exactly on the margin prints its first letter partly off the sheet — capa6
    lost the T of "Título". Text that overhangs on the right is shrunk rather than moved, so
    it keeps its left axis with everything else.
    """
    left = margin * 0.9
    for el in placed:
        b = el.get("bbox_cm") or {}
        if not b:
            continue
        if b["x"] < left:
            b["x"] = round(left, 3)
        over = (b["x"] + b["w"]) - (W - margin * 0.5)
        if over > 0 and b["w"] > 0:
            pt = max(_MIN_PT, (el.get("font_size_pt") or 10) * (b["w"] - over) / b["w"])
            el["font_size_pt"] = round(pt, 1)
            b["w"] = round(_text_w_cm(el.get("text", ""), pt, el), 3)
            b["h"] = round(pt / _PT_PER_CM, 3)


def _separate(placed: list, W: float, H: float, margin: float) -> None:
    """Pull apart blocks whose zones happen to overlap.

    The poster's text areas were chosen for its own short labels and can sit close together;
    our longer fields expand into each other. Priority decides who moves: the title stays put
    and the later, smaller fields give way — first by stepping aside, then by shrinking.
    """
    for _ in range(60):
        hit = None
        for i in range(len(placed)):
            for j in range(i + 1, len(placed)):
                if _boxes_hit(placed[i], placed[j]):
                    hit = j                       # the later field yields
                    break
            if hit is not None:
                break
        if hit is None:
            return
        el = placed[hit]
        b = el["bbox_cm"]
        drop = b["h"] + 0.14
        if b["y"] - drop >= margin * 0.5:
            b["y"] = round(b["y"] - drop, 3)
            if "baseline_y_cm" in el:
                el["baseline_y_cm"] = round(el["baseline_y_cm"] - drop, 3)
            continue
        pt = (el.get("font_size_pt") or 0) * 0.88
        if pt < _MIN_PT:
            return
        el["font_size_pt"] = round(pt, 1)
        b["w"] = round(_text_w_cm(el.get("text", ""), pt, el), 3)
        b["h"] = round(pt / _PT_PER_CM, 3)




_DEBRIS_MAX_CM2 = 1.6   # a shape this small under our own type is debris, not artwork


def _clear_under_type(out: dict, placed: list) -> None:
    """Drop small artwork shapes that sit under the block WE just set.

    Some of the poster's own letterforms reach the regions as little traced shapes without
    ever being reported by the OCR — capa8 keeps a ghostly "the velvet" that no text box
    covers, so the box-based filter cannot see it. Once our imprint is placed, anything tiny
    underneath it is debris by definition: we are writing there.

    Only SMALL shapes go. A large region overlapping the block is the ground the block was
    deliberately placed on.
    """
    if not placed:
        return
    x0 = min(e["bbox_cm"]["x"] for e in placed)
    x1 = max(e["bbox_cm"]["x"] + e["bbox_cm"]["w"] for e in placed)
    y0 = min(e["bbox_cm"]["y"] for e in placed)
    y1 = max(e["bbox_cm"]["y"] + e["bbox_cm"]["h"] for e in placed)

    keep = []
    for r in (out.get("regions") or []):
        b = r.get("bbox_cm") or {}
        area = b.get("w", 0) * b.get("h", 0)
        if area <= 0 or area > _DEBRIS_MAX_CM2:
            keep.append(r)
            continue
        ov = (max(0.0, min(b["x"] + b["w"], x1) - max(b["x"], x0))
              * max(0.0, min(b["y"] + b["h"], y1) - max(b["y"], y0)))
        if ov / area < 0.6:
            keep.append(r)
    out["regions"] = keep


def _drop_traced_type(out: dict, originals: list) -> None:
    """Remove artwork regions that are really the POSTER'S OWN LETTERS.

    The reader traces ink, and where the OCR mask misses a word the letterforms come through
    as little shapes. In the replica that is correct — the poster does have those words. In
    this version it is not: we removed the poster's text and put ours in, so leftover glyph
    shapes read as debris. capa8 kept a ghostly "the velvet" under our own title.

    A region is dropped only when it sits INSIDE a box the OCR reported as text and is small
    — a big shape overlapping a caption is artwork the caption was placed on.
    """
    boxes = [e.get("bbox_cm") or {} for e in originals]
    if not boxes:
        return
    keep = []
    for r in (out.get("regions") or []):
        b = r.get("bbox_cm") or {}
        area = b.get("w", 0) * b.get("h", 0)
        if not b or area <= 0 or area > 12.0:
            keep.append(r)
            continue
        # How much of this shape lies inside a box the OCR called text? Judging by CONTAINMENT
        # alone missed capa8: its traced letterforms are wider than the reported caption box,
        # so none of them was fully inside and the ghost survived.
        cov = 0.0
        for tb in boxes:
            if not tb:
                continue
            ov = (max(0.0, min(b["x"] + b["w"], tb["x"] + tb["w"]) - max(b["x"], tb["x"]))
                  * max(0.0, min(b["y"] + b["h"], tb["y"] + tb["h"]) - max(b["y"], tb["y"])))
            cov += ov
        if cov / area < 0.55:
            keep.append(r)
    out["regions"] = keep


def _text_zones(originals: list, W: float, H: float, margin: float) -> list:
    """The poster's own text areas, as empty boxes ranked by prominence.

    Its designer already decided where type belongs on this artwork; those decisions are the
    best anchors we have. Lines that read as one block collapse into one zone, and the zone
    keeps how many lines it held so a two-line slot still takes two lines.
    """
    if not originals:
        return []
    zones = []
    for blk in group_blocks(originals):
        els = [originals[i] for i in blk]
        x = min((e.get("bbox_cm") or {}).get("x", 0) for e in els)
        top = max((e.get("bbox_cm") or {}).get("y", 0) + (e.get("bbox_cm") or {}).get("h", 0)
                  for e in els)
        bot = min((e.get("bbox_cm") or {}).get("y", 0) for e in els)
        pt = max((e.get("font_size_pt") or 0) for e in els)
        zones.append({"x": max(margin * 0.55, x), "top": top, "bottom": bot,
                      "width": max(2.0, W - max(margin * 0.55, x) - margin * 0.55),
                      "lines": len(els), "pt": pt,
                      "height": max(pt / _PT_PER_CM, top - bot)})
    return sorted(zones, key=lambda z: -z["pt"])


def _fallback_zone(analysis: dict, render_path, W, H, margin) -> list:
    """Three stacked zones for artwork that carries no type of its own (capa3 is op-art).

    They must be laid out with real vertical separation. Handing all three the same top let
    title, subtitle and imprint pile onto the same baseline, and the separation pass could
    only shrink them because there was nowhere left to move.
    """
    try:
        runs = _calm_runs(_row_calm(render_path, W, H), H)
    except Exception:
        runs = []
    if runs:
        bot, top, height, _ = max(runs, key=lambda r: r[2])
    else:
        bot, top, height = margin, H * 0.42, H * 0.42 - margin
    top = min(top - 0.4, H - margin)
    bot = max(bot, margin * 0.6)
    usable = max(3.0, top - bot)

    # Title takes the upper half of the band, subtitle and imprint the rest.
    t_h = usable * 0.42
    s_h = usable * 0.16
    return [
        {"x": margin, "top": top, "bottom": top - t_h, "width": W - 2 * margin,
         "lines": 2, "pt": 66.0, "height": t_h},
        {"x": margin, "top": top - t_h - usable * 0.06, "bottom": bot,
         "width": W - 2 * margin, "lines": 1, "pt": 20.0, "height": s_h},
        {"x": margin, "top": top - t_h - s_h - usable * 0.16, "bottom": bot,
         "width": (W - 2 * margin) * 0.6, "lines": 5, "pt": 11.0,
         "height": max(1.8, usable * 0.3)},
    ]



_TITLE_FLOOR_PT = 26.0   # below this a book title stops reading as a title
_TITLE_GROWN_MAX = 92.0  # ...and this is as far as it may grow when it takes extra width


def _widest_flat_run(analysis: dict, y: float, W: float, margin: float) -> tuple:
    """The widest stretch of ONE flat colour across the page at height `y`, as (x, width).

    Used only to rescue a title that the poster's own zone would leave illegible. The user's
    rule: the title may take more width than the poster reserved, but only across flat
    colour — never across pattern, and never by covering the artwork.
    """
    def key(hx):
        hx = (hx or "").lstrip("#")
        try:
            return tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))
        except Exception:
            return None

    regions = [r for r in (analysis.get("regions") or []) if r.get("bbox_cm")]
    page = next((c.get("hex") for c in sorted((analysis.get("colors") or []),
                                              key=lambda c: -(c.get("coverage") or 0))), "#FFF")
    n, x0, span = 160, margin * 0.55, W - 2 * margin * 0.55
    marks = []
    for i in range(n):
        px = x0 + span * (i + 0.5) / n
        top = page
        for r in regions:
            rb = r["bbox_cm"]
            if rb["x"] <= px <= rb["x"] + rb["w"] and rb["y"] <= y <= rb["y"] + rb["h"]:
                top = r.get("color_hex") or top
        marks.append(key(top))

    best, i = (0, 0), 0
    while i < n:
        j = i
        while j + 1 < n and marks[j + 1] == marks[i]:
            j += 1
        if j - i + 1 > best[0]:
            best = (j - i + 1, i)
        i = j + 1
    run, a = best
    return x0 + span * a / n, max(2.0, span * run / n)


def _shrink_to_zone(value: str, zone: dict, proto: dict, lines_wanted: int) -> tuple:
    """Set `value` inside the zone. The TYPE gives, never the artwork.

    The poster held "david bowie" — eleven characters — where we must put twenty-three. The
    user's call was explicit: shrink. So the size starts at what the poster used and comes
    down until the words fit the zone's width in the lines it allows. The artwork underneath
    is never touched and never covered.
    """
    for n in range(lines_wanted, 0, -1):
        lines = [ln for ln in _wrap(value, n) if ln] or [value]
        longest = max(len(ln) for ln in lines)
        pt = min(zone["pt"], zone["width"] * _PT_PER_CM
                 / (longest * _CHAR_EM * (proto.get("hscale") or _HSCALE)))
        if pt >= _MIN_PT and n * pt * _LEADING / _PT_PER_CM <= zone["height"] + 0.35:
            return pt, lines
    lines = [ln for ln in _wrap(value, lines_wanted) if ln] or [value]
    longest = max(len(ln) for ln in lines)
    pt = max(_MIN_PT, min(zone["pt"], zone["width"] * _PT_PER_CM
                          / (longest * _CHAR_EM * (proto.get("hscale") or _HSCALE))))
    return pt, lines


def _single_ground_span(analysis: dict, zone: dict, y: float) -> tuple:
    """Widest run across the zone that sits on ONE colour, as (x, width).

    Type that straddles an edge has no good single colour — capa19's title crosses the black
    form into the yellow and any one ink is wrong for half of it. Since the artwork may not
    be covered and the user's rule is that the TYPE gives, the zone shrinks to the widest
    stretch of a single ground and the words are set inside that.
    """
    def lum_hex(hx):
        hx = (hx or "").lstrip("#")
        try:
            return sum(int(hx[i:i + 2], 16) for i in (0, 2, 4))
        except Exception:
            return None

    regions = [r for r in (analysis.get("regions") or []) if r.get("bbox_cm")]
    page = next((c.get("hex") for c in sorted((analysis.get("colors") or []),
                                              key=lambda c: -(c.get("coverage") or 0))), "#FFF")
    n = 48
    marks = []
    for i in range(n):
        px = zone["x"] + zone["width"] * (i + 0.5) / n
        top = page
        for r in regions:
            rb = r["bbox_cm"]
            if rb["x"] <= px <= rb["x"] + rb["w"] and rb["y"] <= y <= rb["y"] + rb["h"]:
                top = r.get("color_hex") or top
        marks.append(lum_hex(top))

    best = (0, 0, 0)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and marks[j + 1] == marks[i]:
            j += 1
        if j - i + 1 > best[0]:
            best = (j - i + 1, i, j)
        i = j + 1
    run, a, b = best
    if run >= n * 0.9:
        return zone["x"], zone["width"]
    x0 = zone["x"] + zone["width"] * a / n
    return x0, max(2.0, zone["width"] * run / n)


def _stack_in_zone(values: list, zone: dict, proto: dict) -> tuple:
    """Set several short fields as one stack inside a single zone."""
    lines = []
    for v in values:
        lines.append(v)
    longest = max(len(ln) for ln in lines)
    pt = min(zone["pt"], zone["width"] * _PT_PER_CM
             / (longest * _CHAR_EM * (proto.get("hscale") or _HSCALE)))
    room = max(zone["height"], 1.2)
    while pt > _MIN_PT and len(lines) * pt * _META_LEAD / _PT_PER_CM > room + 1.6:
        pt *= 0.92
    return max(_MIN_PT, pt), lines


def _mark_slot(out: dict, source: dict, placed: list, W, H, margin, render_path) -> dict:
    """Where the Versatus mark goes: the measured spot if the poster HAS one, else adapted.

    The user asked for both — fixed where we established a logo belongs, and placed sensibly
    per cover elsewhere. A poster whose own mark the pipeline located (capa1, capa7, capa14)
    tells us exactly where a mark reads on that composition; the rest get the quietest corner
    that no type is using.
    """
    for lg in (source.get("logos") or []):
        b = lg.get("bbox_cm") or {}
        if b.get("w"):
            return {"x": b["x"], "y": b["y"], "w": b["w"],
                    "h": b.get("h", b["w"] * 0.34), "source": "medido"}
    for el in (source.get("text_elements") or []):
        if is_logo_placeholder(el.get("text", "")) and (el.get("bbox_cm") or {}).get("w"):
            b = el["bbox_cm"]
            return {"x": b["x"], "y": b["y"], "w": max(b["w"], W * 0.18),
                    "h": max(b["w"], W * 0.18) * 0.34, "source": "placeholder"}

    lw = W * _LOGO_W_FRAC
    # Real aspect from the brand artwork. Assuming 0.34 made the reserved box shorter than
    # the mark actually draws, so the collision test passed and the logo still printed on
    # top of the imprint.
    _bl = brand_logo("versatus", "light") or {}
    lh = lw * ((_bl.get("h") or 1.0) / (_bl.get("w") or 3.0))
    try:
        calm = _row_calm(render_path, W, H)
    except Exception:
        calm = []
    corners = [(margin, H - margin - lh), (W - margin - lw, H - margin - lh),
               (margin, margin), (W - margin - lw, margin)]
    best, best_score = None, None
    for cx, cy in corners:
        pad = margin * 0.45      # touching is not clearance; the mark needs air around it
        probe = {"bbox_cm": {"x": cx - pad, "y": cy - pad,
                             "w": lw + 2 * pad, "h": lh + 2 * pad}}
        if any(_boxes_hit(probe, e) for e in placed):
            continue
        spread = 999.0
        if calm:
            r0 = int((1 - (cy + lh) / H) * len(calm))
            r1 = int((1 - cy / H) * len(calm))
            sl = calm[max(0, r0):max(1, r1)]
            spread = sum(sl) / len(sl) if sl else 999.0
        if best_score is None or spread < best_score:
            best, best_score = (cx, cy), spread
    if best is None:
        best = (W - margin - lw, margin)
    return {"x": round(best[0], 2), "y": round(best[1], 2),
            "w": round(lw, 2), "h": round(lh, 2), "source": "adaptado"}


# ─── Refino por VLM (passe pós texto+logo) ────────────────────────────────────

_REFINE_SYSTEM = (
    "You are a Swiss-style book cover typographer. The ARTWORK of this cover is FIXED and "
    "must not change — you are only allowed to adjust the TYPE and the LOGO that were placed "
    "on top of it. Judge the page as a designer would: hierarchy (the title must dominate), "
    "alignment (Swiss layouts align to a small number of vertical guides), grouping (related "
    "information sits together with consistent size), legibility (type must not sit on busy "
    "pattern or on a ground of similar value), and breathing room. "
    "Return ONLY JSON: {\"edits\":[...]}. Never invent text; never move artwork."
)

_REFINE_OPS = {"text.move", "text.size", "text.color", "text.weight", "logo.move"}
_REFINE_MIN_PT, _REFINE_MAX_PT = 6.0, 200.0
_LEGIBILITY_TOL = 4.0   # a hair of slack; anything more is a real loss of readability


def _refine_context(analysis: dict) -> str:
    """Describe the current placement as DATA the VLM can edit by index."""
    W = analysis["canvas"]["width_cm"]
    H = analysis["canvas"]["height_cm"]
    lines = [
        f"CANVAS: {W} x {H} cm. Origin (0,0) is the BOTTOM-LEFT; y grows upward.",
        "",
        "TEXT ELEMENTS currently on the cover (index, position of the box's bottom-left, "
        "size, colour, string):",
    ]
    for i, el in enumerate(analysis.get("text_elements") or []):
        b = el.get("bbox_cm") or {}
        lines.append(
            f"  [{i}] x={b.get('x', 0):.2f} y={b.get('y', 0):.2f} w={b.get('w', 0):.2f} "
            f"h={b.get('h', 0):.2f} {el.get('font_size_pt', 0):.1f}pt "
            f"{el.get('weight_hint', 'regular')} {el.get('color_hex', '')} "
            f"\"{el.get('text', '')}\"")
    lg = (analysis.get("integration") or {}).get("logo") or {}
    slot = lg.get("slot") or {}
    lines += [
        "",
        f"LOGO: x={slot.get('x', 0):.2f} y={slot.get('y', 0):.2f} w={slot.get('w', 0):.2f} "
        f"h={slot.get('h', 0):.2f} variant={lg.get('variant')} (placed by: "
        f"{slot.get('source')})",
        "",
        "PALETTE (colours that exist in this design): "
        + ", ".join(c.get("hex", "") for c in (analysis.get("colors") or [])[:10]),
        "",
        "ALLOWED EDITS — data only, one JSON object each:",
        '  {"op":"text.move","id":N,"dx_cm":F,"dy_cm":F}',
        '  {"op":"text.size","id":N,"font_size_pt":F}',
        '  {"op":"text.color","id":N,"hex":"#RRGGBB"}     (must be readable on its ground)',
        '  {"op":"text.weight","id":N,"weight":"bold"|"regular"}',
        '  {"op":"logo.move","x_cm":F,"y_cm":F,"w_cm":F}',
        "",
        "Priorities, in order: (1) nothing may overlap anything; (2) the title must be the "
        "clearly dominant element; (3) type must sit on a calm, contrasting ground — move it "
        "off busy pattern rather than recolouring it; (4) items that belong together share a "
        "left edge and a size; (5) the logo sits in quiet space, clear of all type.",
    ]
    return "\n".join(lines)


def propose_refinements(analysis: dict, render_path, max_edits: int = 14,
                        mock: "list | None" = None) -> list:
    """Ask the VLM to critique the INTEGRATED page. Only the render is sent — deliberately.

    The existing `vlm_proposer.propose` shows the original poster as the TARGET and asks the
    model to close the gap. That is the wrong question here: the content changed on purpose,
    so 'looks less like the poster' is not an error. What we want judged is whether the page
    works as a cover now.
    """
    if mock is not None:
        return mock[:max_edits]

    import importlib.util
    from google import genai              # noqa: PLC0415
    from google.genai import types        # noqa: PLC0415

    spec = importlib.util.spec_from_file_location(
        "vision_extractor", ROOT / "automation" / "scripts" / "vision_extractor.py")
    ve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ve)

    client = genai.Client(http_options={"api_version": "v1beta"})
    parts = [
        types.Part(text="The cover as it currently stands:"),
        types.Part(inline_data=types.Blob(data=Path(render_path).read_bytes(),
                                          mime_type="image/png")),
        types.Part(text=_refine_context(analysis)
                   + f"\n\nPropose at most {max_edits} edits, most important first."),
    ]
    vp_spec = importlib.util.spec_from_file_location(
        "vlm_proposer", ROOT / "automation" / "scripts" / "vlm_proposer.py")
    vp = importlib.util.module_from_spec(vp_spec)
    vp_spec.loader.exec_module(vp)

    last = None
    for model in ve._resolve_model_chain():
        try:
            txt = ve._call_gemini(parts, _REFINE_SYSTEM, model, client)
            return vp._edits_from_text(txt)[:max_edits]
        except Exception as exc:
            last = exc
    raise RuntimeError(f"todos os modelos Gemini falharam: {last}")


def legibility(analysis: dict, el: dict) -> float:
    """How readable is this element WHERE IT SITS? Higher is better.

    Two things decide it, and both are measurable from the regions: the contrast between the
    type and the worst ground it touches, and how many different grounds it touches at all.
    A title lying across a diamond lattice alternates between four colours — no single ink is
    readable on all of them, and the answer is to MOVE the type to calm ground, not to recolour.

    This exists because the constraint gate alone was not enough. On capa16 the VLM's twelve
    edits each satisfied "on canvas, no overlap" and together dragged the title onto the
    pattern, where it disappeared. "Does not collide" is not the same as "can be read".
    """
    b = el.get("bbox_cm") or {}
    if not b.get("w"):
        return 0.0
    W = analysis["canvas"]["width_cm"]
    H = analysis["canvas"]["height_cm"]

    def lum_hex(h):
        h = (h or "").lstrip("#")
        try:
            r, g, bl = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        except Exception:
            return None
        return 0.299 * r + 0.587 * g + 0.114 * bl

    regions = [r for r in (analysis.get("regions") or []) if r.get("bbox_cm")]
    page_bg = next((lum_hex(c.get("hex")) for c in
                    sorted((analysis.get("colors") or []),
                           key=lambda c: -(c.get("coverage") or 0))
                    if lum_hex(c.get("hex")) is not None), 255.0)

    grounds = []
    for i in range(_BG_SAMPLES):
        px = b["x"] + b["w"] * (i + 0.5) / _BG_SAMPLES
        py = b["y"] + b.get("h", 0.2) * 0.5
        top = page_bg
        for r in regions:
            rb = r["bbox_cm"]
            if (rb["x"] <= px <= rb["x"] + rb["w"] and rb["y"] <= py <= rb["y"] + rb["h"]):
                L = lum_hex(r.get("color_hex"))
                if L is not None:
                    top = L
        grounds.append(top)

    ink = lum_hex(el.get("color_hex"))
    if ink is None or not grounds:
        return 0.0
    worst = min(abs(ink - g) for g in grounds)
    distinct = len({round(g / 12) for g in grounds})       # 12 units ~ one visible step
    edge = min(b["x"], W - (b["x"] + b["w"]), b["y"], H - (b["y"] + b["h"]))
    return worst / (1.0 + 0.6 * (distinct - 1)) - (0.0 if edge >= 0.4 else 40.0)


def apply_refinements(analysis: dict, edits: list) -> tuple:
    """Apply the VLM's edits one at a time, keeping only those that break no hard rule.

    The usual measured gate compares against the original poster, which cannot judge this
    page — the content is meant to differ. So the gate here is a set of constraints that CAN
    be checked: stay on the canvas, do not overlap, keep enough contrast, keep a sane size.
    Inside those walls the model's design judgement is what we are buying.
    """
    els = analysis.get("text_elements") or []
    W = analysis["canvas"]["width_cm"]
    H = analysis["canvas"]["height_cm"]
    kept, dropped = [], []

    def violates(idx) -> "str | None":
        e = els[idx]
        b = e.get("bbox_cm") or {}
        if b["x"] < 0 or b["y"] < 0 or b["x"] + b["w"] > W or b["y"] + b["h"] > H:
            return "sai da pagina"
        for j, other in enumerate(els):
            if j != idx and _boxes_hit(e, other):
                return f"sobrepoe [{j}]"
        pt = e.get("font_size_pt") or 0
        if not (_REFINE_MIN_PT <= pt <= _REFINE_MAX_PT):
            return f"corpo fora de faixa ({pt:.0f}pt)"
        return None

    for ed in edits:
        op = (ed.get("op") or "").strip()
        if op not in _REFINE_OPS:
            dropped.append((ed, "op desconhecida"))
            continue

        if op == "logo.move":
            slot = ((analysis.get("integration") or {}).get("logo") or {}).get("slot")
            if not slot:
                dropped.append((ed, "sem slot de logo"))
                continue
            before = dict(slot)
            for key, field in (("x_cm", "x"), ("y_cm", "y"), ("w_cm", "w")):
                if ed.get(key) is not None:
                    slot[field] = float(ed[key])
            slot["h"] = slot["w"] * (before["h"] / before["w"] if before.get("w") else 0.34)
            bad = (slot["x"] < 0 or slot["y"] < 0 or slot["x"] + slot["w"] > W
                   or slot["y"] + slot["h"] > H
                   or _hits_text(analysis, slot["x"], slot["y"], slot["w"], slot["h"]))
            if bad:
                slot.clear()
                slot.update(before)
                dropped.append((ed, "logo sairia da pagina ou cairia no texto"))
            else:
                slot["source"] = "vlm"
                kept.append(ed)
            continue

        idx = ed.get("id")
        if not isinstance(idx, int) or not (0 <= idx < len(els)):
            dropped.append((ed, "id invalido"))
            continue
        el = els[idx]
        snapshot = json.loads(json.dumps(el))
        before_leg = legibility(analysis, el)

        if op == "text.move":
            b = el["bbox_cm"]
            b["x"] = round(b["x"] + float(ed.get("dx_cm") or 0), 3)
            b["y"] = round(b["y"] + float(ed.get("dy_cm") or 0), 3)
            if "baseline_y_cm" in el:
                el["baseline_y_cm"] = round(el["baseline_y_cm"] + float(ed.get("dy_cm") or 0), 3)
        elif op == "text.size":
            pt = float(ed.get("font_size_pt") or 0)
            el["font_size_pt"] = round(pt, 1)
            b = el["bbox_cm"]
            b["w"] = round(_text_w_cm(el.get("text", ""), pt, el), 3)
            b["h"] = round(pt / _PT_PER_CM, 3)
        elif op == "text.color":
            hexv = str(ed.get("hex") or "")
            if len(hexv.lstrip("#")) != 6:
                dropped.append((ed, "cor invalida"))
                continue
            el["color_hex"] = "#" + hexv.lstrip("#").upper()
        elif op == "text.weight":
            el["weight_hint"] = "bold" if str(ed.get("weight")) == "bold" else "regular"

        why = violates(idx)
        if not why:
            # Constraints are necessary, not sufficient: an edit that satisfies all of them
            # can still drag the type onto pattern. Legibility must not go DOWN.
            after = legibility(analysis, els[idx])
            if after < before_leg - _LEGIBILITY_TOL:
                why = f"legibilidade cai {before_leg:.0f} -> {after:.0f}"
        if why:
            els[idx] = snapshot
            dropped.append((ed, why))
        else:
            kept.append(ed)

    return kept, dropped


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    meta = parse_metadata()
    if len(sys.argv) < 2:
        print("metadata:", json.dumps(meta, ensure_ascii=False, indent=2))
        raise SystemExit(0)
    args = sys.argv[1:]
    refine = "--refine" in args          # let the VLM criticise the finished page
    refresh = "--refresh" in args        # ...and actually call the API instead of the cache
    rounds = 2 if "--rounds=2" in args else 1
    for n in [a for a in args if not a.startswith("--")]:
        print(f"capa{n}:")
        res = (build_refined(n, rounds=rounds, refresh=refresh) if refine else build(n))
        if not res["ok"]:
            print(f"   FALHOU — {res['error']}")
            continue
        info = res["info"]
        print(f"   {len(info['fields_placed'])} slots com conteudo, "
              f"{len(info['slots_kept_original'])} mantidos, "
              f"logo {info['logo']['variant']} ({info['logo']['slot']['source']}) "
              f"-> {res['png'].name}")
