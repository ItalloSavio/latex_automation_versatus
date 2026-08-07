#!/usr/bin/env python3
"""
edit_gate.py — the GATEKEEPER: typed edits + two-layer hallucination filter (Fase 5).

A PROPOSER (the VLM, or a fake one for testing) suggests TYPED EDITS against the
analysis. This module is the intermediary that only lets through what actually improves
the render. It is PROPONENT-AGNOSTIC — the VLM never touches the project directly; it
speaks only in edits, and this gate judges them the same way the loop already judges the
calibrator/patch. That is what contains hallucination.

Two layers per edit:
  ① grounding — cheap, NO render: is the edit plausible vs the evidence? (id exists,
                colour near the palette, coords in canvas, string fits the box)
  ② measured  — hill-climb: apply → render → measure with the ROUTED metric
                (geometry → score ; text → text_match); keep only if the primary metric
                rises AND no guarded metric regresses. Never worse than the input.

Edit schema (op + params), referencing elements by a stable `_id`:
  text.string {id,value} · text.move {id,dx_cm,dy_cm} · text.hscale {id,value}
  region.color {id,hex} · region.move {id,dx_cm,dy_cm} · region.resize {id,w_cm,h_cm}
  region.remove {id} · region.add {shape,hex,points_cm|bbox_cm} · vocab.gap {bbox_cm,describe}

Demo (a FAKE proposer — validates the whole machine with NO VLM):
    python automation/scripts/edit_gate.py 7
"""

import copy
import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve().parent

_GROUND_COLOR_TOL = 70       # a proposed hex must be within this RGB dist of the palette
_ACCEPT_EPS       = 1e-3     # primary metric must rise by at least this to accept
_GUARD_EPS        = 5e-3     # a guarded metric may not fall by more than this
_PT_PER_CM        = 72.0 / 2.54                 # points per cm (for text.add font size)
_TEXT_OPS = {"text.string", "text.move", "text.hscale", "text.add"}

# Em ratios for sizing a font from MEASURED ink height (same model as ocr_extractor):
# ascender→baseline ≈ 0.735·em; ascender→descender ≈ 0.945·em. Which one applies is decided
# by the STRING, deterministically — we know what the VLM read.
_ASCENDER_EM = 0.735
_ASC_DESC_EM = 0.945
_DESC_CHARS  = set("gjpqyçÇ,;()[]{}@$_")

# Grounded edits the EYE clearly wants but the pixel metric is BLIND to: a fixed OCR string,
# a thin rule / shape that's in the original. content_match barely moves (or dips sub-pixel)
# on these, so demanding it RISE wrongly reverts correct elements (the "Score green, eye red"
# trap). For these we trust the grounding filter and accept unless a metric really REGRESSES
# (a genuinely bad edit moves the metric far more than _GUARD_EPS). Moves/resizes/recolours of
# EXISTING elements stay strict — there the metric IS the right judge of alignment.
_TRUST_OPS = {"text.string", "region.add", "logo.mark"}


# ─── Edit application ──────────────────────────────────────────────────────────

def assign_ids(analysis: dict) -> dict:
    """Give every region/text a stable _id so edits survive removes and reordering."""
    for i, r in enumerate(analysis.get("regions", [])):
        r.setdefault("_id", f"r{i}")
    for i, t in enumerate(analysis.get("text_elements", [])):
        t.setdefault("_id", f"t{i}")
    return analysis


def _find(items: list, _id) -> "dict | None":
    return next((it for it in items if it.get("_id") == _id), None)


def _rgb(hx: str) -> "tuple[int,int,int]":
    hx = hx.lstrip("#")
    return int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)


def _color_near_palette(hx: str, analysis: dict, tol: int = _GROUND_COLOR_TOL) -> bool:
    try:
        rgb = _rgb(hx)
    except Exception:
        return False
    pal = analysis.get("colors", [])
    if not pal:
        return True
    return any(sum((a - b) ** 2 for a, b in zip(rgb, p["rgb"])) ** 0.5 <= tol for p in pal)


def dedup_text(analysis: dict) -> dict:
    """Drop OCR text elements that a VLM text.add OVERLAPS — the OCR read (often a misread,
    e.g. 'Welter Knol' rendered huge) is superseded by the VLM's clean multi-line block sitting
    on the same spot. Keeps the VLM element; removes the deterministic one it covers."""
    texts = analysis.get("text_elements", [])
    vlm = [t for t in texts if t.get("source") == "vlm" and t.get("bbox_cm")]
    if not vlm:
        return analysis
    kept = []
    for t in texts:
        if t.get("source") == "vlm" or not t.get("bbox_cm"):
            kept.append(t); continue
        b = t["bbox_cm"]; cx = b["x"] + b["w"] / 2; cy = b["y"] + b["h"] / 2
        covered = any(v["bbox_cm"]["x"] - 0.5 <= cx <= v["bbox_cm"]["x"] + v["bbox_cm"]["w"] + 0.5
                      and v["bbox_cm"]["y"] - 1.0 <= cy <= v["bbox_cm"]["y"] + v["bbox_cm"]["h"] + 1.0
                      for v in vlm)
        if not covered:
            kept.append(t)
    analysis["text_elements"] = kept
    return analysis


def _glyph_only(win, span_px=0.0):
    """Strip everything that is not glyph-sized from an ink window.

    A region EDGE (capa6's black/orange diagonal) is dark next to a bright neighbour, so it
    passes the ink test — but it is ONE component far taller than any line of the block. The
    height limit comes from the VLM's block height (`span_px`), NOT from the window: a
    window-relative 0.35 killed capa5's "grafik" TITLE, whose letters are 30px in a 75px
    window, and the snap then read the small text below as the title. Not a median over
    components either — a hard edge shatters into hundreds of anti-alias specks and drags
    any median to 1px (that collapsed capa6's middle block)."""
    from scipy import ndimage
    import numpy as np
    h, w = win.shape
    lim = min(max(1.5 * span_px, 12.0), 0.9 * h)        # never keep a window-spanning blob
    lbl, n = ndimage.label(win)
    if n == 0:
        return win
    out = np.zeros_like(win)
    for i, o in enumerate(ndimage.find_objects(lbl)):
        if (o[0].stop - o[0].start) > lim or (o[1].stop - o[1].start) > 0.90 * w:
            continue                                    # too tall / too wide → not a glyph
        sub = lbl[o] == i + 1
        if sub.sum() >= 2:                              # a lone pixel is anti-alias noise
            out[o] |= sub
    return out


def _row_runs(win):
    """Contiguous inked row spans, keeping only those dense and small enough to be a text
    LINE: an edge remnant is sparse (few px per row), a graphic blob is far taller."""
    import numpy as np
    prof = win.sum(1)
    runs, s = [], None
    for i, v in enumerate(prof >= 2):
        if v and s is None:
            s = i
        elif not v and s is not None:
            runs.append((s, i - 1)); s = None
    if s is not None:
        runs.append((s, len(prof) - 1))
    if not runs:
        return []
    dens = np.array([prof[a:b + 1].mean() for a, b in runs])
    hs   = np.array([b - a + 1 for a, b in runs], float)
    return [r for r, d, h in zip(runs, dens, hs)
            if d >= 0.30 * np.median(dens) and h <= 2.5 * np.median(hs)]


def _pick_lines(runs, slots, ctr_row, win_h, span_px=0.0):
    """Choose the N row-runs that best fit `top_i = y0 + slot_i·pitch`.

    `slots` are the line indices INCLUDING blank spacers, so a header gapped from its body
    (capa7 "systems" ⏎⏎ "25 November to") fits the same linear model as an even block. The
    residual of that fit is the anti-hallucination test: real lines of a block sit on a
    regular baseline grid, stray ink does not."""
    import itertools
    import numpy as np
    n = len(slots)
    if len(runs) < n:
        return None
    if n == 1:
        return [min(runs, key=lambda r: abs((r[0] + r[1]) / 2 - ctr_row))]
    A = np.vstack([np.array(slots, float), np.ones(n)]).T
    best, best_cost, best_res = None, 1e9, 1e9
    for grp in itertools.combinations(runs[:9], n):      # cap the search; 9 choose 4 = 126
        tops = np.array([r[0] for r in grp], float)
        sol, *_ = np.linalg.lstsq(A, tops, rcond=None)
        pitch = sol[0]
        if pitch <= 0.5:
            continue
        res = float(np.abs(A @ sol - tops).max()) / pitch
        hs  = np.array([r[1] - r[0] + 1 for r in grp], float)
        # Lines of a block are ADJACENT: real leading runs ~1.2–2.2× the glyph height. Without
        # this the fit is vacuous for a 2-line block (a straight line through 2 points always
        # has zero residual), and capa5 SKIPPED "verbandes schweiz. grafiker" to pair line 1
        # with the NEXT block's first line — a pitch of exactly two lines.
        # The VLM misplaces a block but reads its EXTENT well, so its bbox height is a good
        # soft prior on the SPAN. This is what separates capa5's true pair (span 16px vs the
        # VLM's 17px) from the pair that skips a line (26px) — both fit a line exactly.
        span = grp[-1][1] - grp[0][0] + 1
        cost = (res + hs.std() / max(hs.mean(), 1e-6)
                + 1.5 * max(0.0, pitch / max(hs.mean(), 1e-6) - 2.2)
                + (abs(span - span_px) / span_px if span_px > 1 else 0.0)
                + 0.6 * abs((grp[0][0] + grp[-1][1]) / 2 - ctr_row) / max(win_h, 1))
        if cost < best_cost:
            best, best_cost, best_res = list(grp), cost, res
    if best is None or best_res > 0.35:                  # off the baseline grid → not this block
        return None
    return best


def snap_text_adds(edits: list, image_path, canvas: dict) -> list:
    """Refine each text.add's bbox to where the ORIGINAL's TEXT INK actually is (the VLM
    reads the string right but places it imprecisely → box_local fails on position alone).
    Isolates text strokes from solid blocks (dark AND a bright pixel nearby) and measures
    where each LINE sits — per-line box + one measured font per block. Deterministic +
    grounded: the position comes from measured pixels, not a second guess. When the lines
    can't be resolved (too low-res, ink fused with a graphic) it returns the edit UNTOUCHED
    rather than guessing; the gate measures it regardless."""
    try:
        import numpy as np
        from PIL import Image
        from scipy import ndimage
        g = np.asarray(Image.open(image_path).convert("RGB")).astype(float).mean(2)
    except Exception:
        return edits
    hpx, wpx = g.shape
    W = canvas.get("width_cm", 21.0); H = canvas.get("height_cm", 29.7)
    # ink = strokes that CONTRAST with the local bg, in the direction of the text COLOUR:
    # dark text → darker than the bright bg (black-on-orange, gray-on-cream); light text →
    # brighter than the dark bg (capa7 white-on-black). Picking the wrong direction snaps to
    # noise (capa7 "systems" collapsed to box_local 0.148).
    mx = ndimage.maximum_filter(g, size=7)
    mn = ndimage.minimum_filter(g, size=7)
    dark_ink  = (g < mx - 55) & (mx > 100)     # dark strokes on a bright bg
    light_ink = (g > mn + 55) & (mn < 155)     # light strokes on a dark bg
    out = []
    for e in edits:
        if e.get("op") != "text.add" or not e.get("bbox_cm"):
            out.append(e); continue
        hx = e.get("hex", "#000000").lstrip("#")
        bright = (int(hx[0:2], 16) + int(hx[2:4], 16) + int(hx[4:6], 16)) / 3 if len(hx) >= 6 else 0
        ink = light_ink if bright > 128 else dark_ink
        b = e["bbox_cm"]; m = 1.6
        c0 = max(0, int((b["x"] - m) / W * wpx)); c1 = min(wpx, int((b["x"] + b["w"] + m) / W * wpx))
        r0 = max(0, int((H - (b["y"] + b["h"] + m)) / H * hpx)); r1 = min(hpx, int((H - (b["y"] - m)) / H * hpx))
        win = ink[r0:r1, c0:c1]
        if win.sum() < 8:
            out.append(e); continue
        # ── Measure each LINE, don't average the block ────────────────────────────────
        # The whole-ink extent divided by the line count spread capa6's blocks to a 1.56cm
        # leading against a measured 0.60cm (and any edge inside the window inflated the
        # extent further). Banding recovers the real baseline grid. A ONE-line block runs
        # the same path (n=1 = pick the run nearest the VLM box): the old extent tail sized
        # it from the median component height CLAMPED to 8–15pt, which is fine for body copy
        # but crushed capa5's "grafik" TITLE from 43.6pt to 8pt. One measurement model.
        rows_all = [r.strip() for r in e.get("value", "").replace("\\n", "\n").split("\n")]
        while rows_all and not rows_all[0]:
            rows_all.pop(0)
        while rows_all and not rows_all[-1]:
            rows_all.pop()
        slots = [i for i, r in enumerate(rows_all) if r]
        real  = [r for r in rows_all if r]
        span_px = b["h"] / H * hpx
        gwin = _glyph_only(win, span_px)
        # Banding earns its keep on LEADING, which only exists with ≥2 lines. On a lone line
        # it measured WORSE than the extent (capa2's date box_local 0.607→0.389): the em comes
        # from one band via the descender-aware ratio, and when the band clips a thin descender
        # ('j' in "12 de junho") the ratio is the wrong one with no median to dilute it.
        if len(real) >= 2:
            ctr  = ((H - (b["y"] + b["h"] / 2)) / H * hpx) - r0
            sel  = _pick_lines(_row_runs(gwin), slots, ctr, gwin.shape[0], span_px=span_px)
            # a band under 3px is noise, not a measurable glyph (capa5 is 300px wide)
            if sel and min(t - s + 1 for s, t in sel) >= 3:
                gy, gx = np.where(gwin)
                bx0, bw_px = gx.min(), gx.max() - gx.min() + 1
                pts = []
                for txt, (s, t) in zip(real, sel):
                    hcm = (t - s + 1) / hpx * H
                    pts.append(hcm / (_ASC_DESC_EM if any(c in _DESC_CHARS for c in txt)
                                      else _ASCENDER_EM) * _PT_PER_CM)
                # ONE size per block: within a Swiss block the header differs in WEIGHT, not
                # size, and a per-line em is ±1px noisy at these scales. Median is robust.
                pt = max(6.0, round(float(np.median(pts)), 1))
                lines_cm = [{"y": round((hpx - (r0 + t + 1)) / hpx * H, 3),
                             "h": round((t - s + 1) / hpx * H, 3)} for s, t in sel]
                top  = max(l["y"] + l["h"] for l in lines_cm)
                bot  = min(l["y"] for l in lines_cm)
                nx   = min(max((c0 + bx0) / wpx * W, b["x"] - 0.5), b["x"] + 0.5)
                if abs((top + bot) / 2 - (b["y"] + b["h"] / 2)) <= 1.5:   # same clamp as below
                    dx = nx - (c0 + bx0) / wpx * W
                    for l in lines_cm:
                        l["x"] = round(nx, 3)
                        l["w"] = round(min(bw_px / wpx * W + dx, b["w"] + 1.0), 3)
                    out.append({**e, "font_size_pt": pt, "lines_cm": lines_cm,
                                "bbox_cm": {"x": round(nx, 2), "y": round(bot, 2),
                                            "w": lines_cm[0]["w"], "h": round(top - bot, 2)}})
                    continue
        # ── Fallback: the whole-ink EXTENT ────────────────────────────────────────────
        # Trustworthy only when the window really is this text's. If the glyph filter had to
        # discard most of the ink, the window is dominated by a graphic and the extent
        # measures THAT: capa5's "grafik" fuses with a region edge into one 75px blob (84%
        # discarded at 300px wide), and the extent read 5.25cm → the 8–15pt clamp crushed the
        # title to 8pt. There, DON'T GUESS — the VLM's own bbox is the better answer (43.6pt,
        # box_local 0.984). The gate measures the edit either way; unrefined ≠ wrong.
        if gwin.sum() < 0.5 * win.sum():
            out.append(e); continue
        ys, xs = np.where(win)
        ix, iy = c0 + xs.min(), r0 + ys.min()
        iw, ih = (xs.max() - xs.min() + 1), (ys.max() - ys.min() + 1)
        nx = ix / wpx * W; ny = (hpx - (iy + ih)) / hpx * H
        nw = iw / wpx * W; nh = ih / hpx * H
        # CLAMP: the snap is a REFINEMENT, not a relocation — a contaminated read (a diagonal
        # edge near the text) must not move the block off its spot. Left-aligned text sits on a
        # grid margin the VLM gets right, so bound X tightly; Y drifts more, so allow more.
        DX, DY = 0.5, 1.5
        nx = min(max(nx, b["x"] - DX), b["x"] + DX)
        ny = min(max(ny, b["y"] - DY), b["y"] + DY)
        nw = min(nw, b["w"] + 2 * DX)
        nb = {"x": round(nx, 2), "y": round(ny, 2), "w": round(nw, 2), "h": round(nh, 2)}
        # font from the median glyph-component height (cap height ≈ 0.7·em), floored to body size.
        lbl, n = ndimage.label(win)
        gh = float(np.median([s[0].stop - s[0].start for s in ndimage.find_objects(lbl)])) if n else 10
        pt = max(8.0, min(15.0, round(gh / hpx * H * _PT_PER_CM / 0.7, 1)))
        out.append({**e, "bbox_cm": nb, "font_size_pt": pt})
    return out


def ground_edit(analysis: dict, edit: dict) -> "tuple[bool, str]":
    """Layer ①: cheap plausibility filter, no render. Returns (ok, reason)."""
    op = edit.get("op")
    canvas = analysis.get("canvas", {})
    W, H = canvas.get("width_cm", 21.0), canvas.get("height_cm", 29.7)

    if op == "vocab.gap":
        return True, "lacuna registrada"

    if op == "logo.mark":                      # a brand LOGO → placeholder, never reconstruct
        name = edit.get("name", "")
        if not name or not any(c.isalnum() for c in name) or len(name) > 30:
            return False, "logo sem nome válido"
        b = edit.get("bbox_cm")
        if not b:
            return False, "logo sem bbox_cm"
        if b["w"] * b["h"] > 0.25 * W * H:     # a logo isn't half the poster — anti-hallucination
            return False, "bbox de logo grande demais"
        return True, "ok"

    if op == "text.add":                       # inject text the OCR missed (VLM read it)
        b = edit.get("bbox_cm"); v = edit.get("value", "")
        if not b:
            return False, "text.add sem bbox_cm"
        if not v or not any(c.isalnum() for c in v):
            return False, "string vazia/sem alfanumérico"
        if not (-1 <= b.get("x", 0) and b["x"] + b.get("w", 0) <= W + 1
                and -1 <= b.get("y", 0) and b["y"] + b.get("h", 0) <= H + 1):
            return False, "bbox fora do canvas"
        return True, "ok"

    if op in _TEXT_OPS:
        el = _find(analysis.get("text_elements", []), edit.get("id"))
        if el is None:
            return False, f"text id {edit.get('id')} inexistente"
        if op == "text.string":
            v = edit.get("value", "")
            if not v or not any(c.isalnum() for c in v):
                return False, "string vazia/sem alfanumérico"
            box_w = el.get("bbox_cm", {}).get("w", W)
            if len(v) > max(6, box_w * 12):     # loose: ~12 glyphs/cm ceiling
                return False, "string longa demais pra caixa"
        if op == "text.hscale" and not (0.3 <= edit.get("value", 0) <= 1.6):
            return False, "hscale fora de [0.3, 1.6]"
        return True, "ok"

    if op == "region.add":
        if not _color_near_palette(edit.get("hex", ""), analysis):
            return False, f"cor {edit.get('hex')} fora da paleta"
        if edit.get("shape") == "polygon":
            pts = edit.get("points_cm", [])
            if len(pts) < 3:
                return False, "polígono < 3 vértices"
            if any(not (0 <= x <= W and 0 <= y <= H) for x, y in pts):
                return False, "vértice fora do canvas"
        if edit.get("shape") == "hatch":
            bh = edit.get("base_hex")
            if bh and not _color_near_palette(bh, analysis):
                return False, f"base {bh} fora da paleta"
            if not edit.get("bbox_cm"):
                return False, "hatch sem bbox_cm"
        return True, "ok"

    el = _find(analysis.get("regions", []), edit.get("id"))
    if el is None:
        return False, f"region id {edit.get('id')} inexistente"
    if op == "region.color" and not _color_near_palette(edit.get("hex", ""), analysis):
        return False, f"cor {edit.get('hex')} fora da paleta"
    if op in ("region.move", "region.resize"):
        b = dict(el["bbox_cm"])
        if op == "region.move":
            b["x"] += edit.get("dx_cm", 0); b["y"] += edit.get("dy_cm", 0)
        else:
            b["w"] = edit.get("w_cm", b["w"]); b["h"] = edit.get("h_cm", b["h"])
        if not (-1 <= b["x"] and b["x"] + b["w"] <= W + 1
                and -1 <= b["y"] and b["y"] + b["h"] <= H + 1):
            return False, "bbox sai do canvas"
    return True, "ok"


def apply_edit(analysis: dict, edit: dict) -> "dict | None":
    """Return a DEEP COPY of analysis with the edit applied (None if not applicable)."""
    a  = copy.deepcopy(analysis)
    op = edit.get("op")

    if op == "vocab.gap":
        a.setdefault("_vocab_gaps", []).append(edit)   # queued, no visual change
        return a

    if op == "logo.mark":                      # a graphic brand logo → placeholder, NOT drawn
        b = edit.get("bbox_cm")
        if not b or not edit.get("name"):
            return None
        def _in(bb):                           # centre falls inside the logo bbox (+0.5cm halo)
            cx, cy = bb["x"] + bb["w"] / 2, bb["y"] + bb["h"] / 2
            return (b["x"] - 0.5 <= cx <= b["x"] + b["w"] + 0.5
                    and b["y"] - 0.5 <= cy <= b["y"] + b["h"] + 0.5)
        # strip the reconstruction attempts in the logo box (the melted mark + its wordmark)
        a["regions"] = [r for r in a.get("regions", []) if not (r.get("bbox_cm") and _in(r["bbox_cm"]))]
        a["text_elements"] = [t for t in a.get("text_elements", [])
                              if not (t.get("bbox_cm") and _in(t["bbox_cm"]))]
        texts = a.setdefault("text_elements", [])
        texts.append({                          # the placeholder that PROVES we recognised a logo
            "text": f"{edit['name']} (Logo)", "font_size_pt": edit.get("font_size_pt", 10),
            "color_hex": edit.get("hex", "#808080"), "bbox_cm": dict(b),
            "source": "logo", "_id": f"logo{len(texts)}",
        })
        a.setdefault("logos", []).append({"name": edit["name"], "bbox_cm": dict(b)})  # future image
        return a

    if op == "text.add":                       # new text from the VLM's read
        b = edit.get("bbox_cm")
        if not b:
            return None
        rows = [ln.strip() for ln in edit.get("value", "").replace("\\n", "\n").split("\n")]
        while rows and not rows[0]:            # trim leading/trailing blanks…
            rows.pop(0)
        while rows and not rows[-1]:
            rows.pop()
        if not any(rows):
            return None
        texts  = a.setdefault("text_elements", [])
        # MEASURED per-line boxes (snap_text_adds banded the block) — use the real baseline
        # grid instead of an even split, which is what got the leading wrong.
        meas = edit.get("lines_cm")
        if meas and len(meas) == sum(1 for r in rows if r):
            pt = edit.get("font_size_pt", 10.0)
            bold_first = len(meas) >= 2
            for i, (ln, m) in enumerate(zip([r for r in rows if r], meas)):
                texts.append({
                    "text": ln, "font_size_pt": pt, "color_hex": edit.get("hex", "#000000"),
                    "weight_hint": "bold" if i == 0 and bold_first else "regular",
                    "bbox_cm": {"x": m.get("x", b["x"]), "y": m["y"],
                                "w": m.get("w", b["w"]), "h": m["h"]},
                    "source": "vlm", "_id": f"vt{len(texts)}",
                })
            return a
        # …but KEEP interior blank lines as SPACERS — the VLM uses them to gap a header from
        # its body (DESCRIÇÃO / … Material técnico…). Dropping them collapsed the two onto
        # each other. Each row (blank or not) reserves one line_h; blanks emit no element.
        line_h = b.get("h", 0.5) / len(rows)
        pt     = edit.get("font_size_pt") or round(line_h * _PT_PER_CM / 1.3, 1)
        # The extent here is the LAST resort (banding failed), so it may be inflated by a
        # graphic the window swallowed — capa5 spread two 6px lines over 2.17cm each. No
        # typeface leads at more than ~1.6 em, so cap it. Blank spacer rows keep their own
        # slot, so a header still gaps from its body. Only for ≥2 rows: with a single row
        # `line_h` is not a leading at all, it is what seats the line on the box's bottom
        # edge — capping it lifted capa2's right footer onto the rule above it.
        if len(rows) >= 2:
            line_h = min(line_h, 1.6 * pt / _PT_PER_CM)
        # Swiss convention: a MULTI-line block's 1st line is BOLD (a header); a lone line
        # (a date, "01") stays regular — so only bold the first when there are ≥2 real lines.
        bold_first = sum(1 for r in rows if r) >= 2
        first = True
        for i, ln in enumerate(rows):          # row 0 = top of the block (highest y, y-up)
            if not ln:
                continue
            texts.append({
                "text": ln, "font_size_pt": pt, "color_hex": edit.get("hex", "#000000"),
                "weight_hint": "bold" if (first and bold_first) else "regular",
                "bbox_cm": {"x": b["x"], "y": round(b["y"] + b["h"] - (i + 1) * line_h, 3),
                            "w": b["w"], "h": round(line_h, 3)},
                "source": "vlm", "_id": f"vt{len(texts)}",
            })
            first = False
        return a

    if op in _TEXT_OPS:
        el = _find(a.get("text_elements", []), edit["id"])
        if el is None:
            return None
        if op == "text.string":
            el["text"] = edit["value"]
        elif op == "text.move":
            el["bbox_cm"]["x"] += edit.get("dx_cm", 0)
            el["bbox_cm"]["y"] += edit.get("dy_cm", 0)
            if "baseline_y_cm" in el:
                el["baseline_y_cm"] += edit.get("dy_cm", 0)
        elif op == "text.hscale":
            el["hscale"] = edit["value"]
        return a

    regions = a.get("regions", [])
    if op == "region.add":
        pts  = edit.get("points_cm")
        bbox = edit.get("bbox_cm")
        if bbox is None and pts:                    # derive bbox from the vertices
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            bbox = {"x": min(xs), "y": min(ys),
                    "w": max(xs) - min(xs), "h": max(ys) - min(ys)}
        if bbox is None:                            # nothing to place it by → reject
            return None
        new = {"shape_type": edit.get("shape", "polygon"), "color_hex": edit["hex"],
               "source": "vlm", "_id": f"v{len(regions)}", "bbox_cm": bbox}
        if pts:
            new["points_cm"] = pts
        for k in ("base_hex", "period_cm", "line_width_pt", "direction"):  # hatch params
            if k in edit:
                new[k] = edit[k]
        regions.append(new)
        return a

    el = _find(regions, edit["id"])
    if el is None:
        return None
    if op == "region.color":
        el["color_hex"] = edit["hex"]
    elif op == "region.move":
        el["bbox_cm"]["x"] += edit.get("dx_cm", 0)
        el["bbox_cm"]["y"] += edit.get("dy_cm", 0)
    elif op == "region.resize":
        el["bbox_cm"]["w"] = edit.get("w_cm", el["bbox_cm"]["w"])
        el["bbox_cm"]["h"] = edit.get("h_cm", el["bbox_cm"]["h"])
    elif op == "region.remove":
        a["regions"] = [r for r in regions if r.get("_id") != edit["id"]]
    return a


# ─── The gate (layer ② + metric routing) ───────────────────────────────────────

_TEXT_ADD_MIN       = 0.35     # a text.add is kept if its OWN box's ink match clears this
_TEXT_ADD_SCORE_TOL = 0.02     # box_local (≥floor) is the JUDGE of a text.add; the global Score
                               # is BLIND to thin text (a well-placed block still dips content
                               # ~0.005 from sub-pixel), so the Score guard is generous — it only
                               # catches a real collapse. Tight 5e-3 wrongly killed capa7's blocks.


def _primary(op: str) -> str:
    return "text_match" if op in _TEXT_OPS else "score"


def _improved(before: dict, after: dict, op: str) -> "tuple[bool, str]":
    """Accept iff the PRIMARY metric rose and no guarded metric fell. Routes text→
    text_match, geometry→score; falls back to score when text_match is absent."""
    if op == "text.add":
        # Adding boxes dilutes the text_match MEAN, and small text barely moves the global
        # score, so judge the addition by the ADDED boxes' OWN ink match (the last N in
        # text_box_scores) — keep it if that clears the floor AND geometry isn't wrecked.
        bs, as_ = before.get("text_box_scores") or [], after.get("text_box_scores") or []
        n_added = max(1, len(as_) - len(bs))
        local   = sum(as_[-n_added:]) / n_added if as_ else 0.0
        sb, sa  = before.get("score", 0.0), after.get("score", 0.0)
        ok = local >= _TEXT_ADD_MIN and sa >= sb - _TEXT_ADD_SCORE_TOL
        return ok, f"box_local {local:.3f} x{n_added} (score {sb:.4f}->{sa:.4f})"

    prim = _primary(op)
    b_p, a_p = before.get(prim), after.get(prim)
    if b_p is None or a_p is None:                    # no text boxes → judge by score
        prim, b_p, a_p = "score", before.get("score"), after.get("score")
    delta = f"{prim} {b_p}→{a_p}"

    if op in _TRUST_OPS:                               # grounded + eye-wanted → trust grounding
        for g in ("score", "text_match"):             # accept unless a metric really regresses
            gb, ga = before.get(g), after.get(g)
            if gb is not None and ga is not None and ga < gb - _GUARD_EPS:
                return False, delta + f" ({g} caiu {gb}→{ga})"
        return True, delta + " [trust]"

    if a_p < b_p + _ACCEPT_EPS:
        return False, delta
    for g in ("score", "text_match"):                 # guard the other metric
        if g == prim:
            continue
        gb, ga = before.get(g), after.get(g)
        if gb is not None and ga is not None and ga < gb - _GUARD_EPS:
            return False, delta + f" (mas {g} caiu {gb}→{ga})"
    return True, delta


def run_gate(analysis: dict, edits: list, measure, log: "list | None" = None):
    """Hill-climb the proposed edits through both layers. `measure(a)` → quality dict
    (must include 'score' and 'text_match'). Returns (best_analysis, best_quality, log)."""
    log = log if log is not None else []
    analysis = assign_ids(copy.deepcopy(analysis))
    best_q = measure(analysis)
    if best_q is None:
        raise RuntimeError("baseline não renderizou")

    for edit in edits:
        op = edit.get("op", "?")
        ok, reason = ground_edit(analysis, edit)
        if not ok:
            log.append({"op": op, "verdict": "✗ aterramento", "info": reason})
            continue
        if op == "vocab.gap":
            analysis = apply_edit(analysis, edit)
            log.append({"op": op, "verdict": "→ fila vocab", "info": edit.get("describe", "")})
            continue
        if op == "logo.mark":
            # A SCOPE decision, not a fidelity edit: the "<Name> (Logo)" placeholder never
            # matches the real logo's ink, so measuring it (text_match) would always reject it.
            # Trust the grounding (the VLM recognised a logo) + the size cap — apply, don't measure.
            cand = apply_edit(analysis, edit)
            if cand is not None:
                analysis, best_q = cand, (measure(cand) or best_q)
                log.append({"op": op, "verdict": "✓ ACEITO", "info": f"placeholder '{edit.get('name')} (Logo)'"})
            else:
                log.append({"op": op, "verdict": "✗ render/aplicação", "info": "n/a"})
            continue
        cand = apply_edit(analysis, edit)
        q = measure(cand) if cand is not None else None
        if q is None:
            log.append({"op": op, "verdict": "✗ render/aplicação", "info": "n/a"})
            continue
        good, delta = _improved(best_q, q, op)
        if good:
            analysis, best_q = cand, q
            log.append({"op": op, "verdict": "✓ ACEITO", "info": delta})
        else:
            log.append({"op": op, "verdict": "↩ revertido", "info": delta})
    return analysis, best_q, log


# ─── FAKE-proposer demo (validates the machine with NO VLM) ─────────────────────

def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def persist_vocab_gaps(analysis: dict, cover: str) -> int:
    """Peça 5 — the vocabulary queue: append the gaps the gate collected to a durable
    file the DEV reviews to grow the vocabulary by MEASURED demand. Returns the count."""
    import json
    gaps = analysis.get("_vocab_gaps", [])
    if not gaps:
        return 0
    out = _HERE.parent / "output" / "vocab_gaps.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "a", encoding="utf-8") as fh:
        for g in gaps:
            fh.write(json.dumps({"cover": cover, **g}, ensure_ascii=False) + "\n")
    return len(gaps)


def cover_measure(n: int):
    """Build (analysis, measure, paths) for one cover, reusing the real render pipeline.
    `measure(a)` renders an analysis and returns its quality dict. Shared by the FAKE
    demo and the VLM proposer so both drive the exact same gate."""
    import json
    rc  = _load("replicate_cover")
    gen = _load("tikz_generator")
    vc  = _load("visual_comparator")
    root = _HERE.parent.parent
    img  = root / "capas_teste" / f"capa_teste{n}.png"
    cdir = _HERE.parent / "output" / "replicated" / f"capa_teste{n}"
    analysis = assign_ids(json.load(open(cdir / "analysis.json", encoding="utf-8")))
    W = analysis["canvas"]["width_cm"]; H = analysis["canvas"]["height_cm"]
    tikz, tex, pdf = cdir / "gate.tikz", cdir / "gate.tex", cdir / "gate.pdf"
    png = cdir / "gate_render.png"

    def measure(a):
        gen.generate(a, tikz)
        rc._write_tex_wrapper(tex, tikz, a, W, H)
        ok, _ = rc._compile_lualatex(tex, pdf)
        if not ok or rc._render_pdf(pdf, png, 150) is None:
            return None
        return vc.compare(str(img), str(png), analysis=a, output_dir=cdir)

    return analysis, measure, {"img": img, "render": png, "cover_dir": cdir}


def _demo(n: int) -> None:
    analysis, measure, _ = cover_measure(n)

    # A controlled test set exercising every verdict, with no VLM:
    #  • a hallucinated colour outside the palette  → layer ① rejects
    #  • a big pointless move                        → layer ② reverts
    #  • DAMAGE a text string, then REPAIR it        → the repair is ACCEPTED (text gate)
    txt0 = analysis["text_elements"][0]
    original_str = txt0["text"]
    analysis["text_elements"][0]["text"] = "ZZZZZ"        # damage (baseline is now wrong)
    reg0 = analysis["regions"][0]["_id"]
    edits = [
        {"op": "region.color", "id": reg0, "hex": "#00FF00"},              # ① reject
        {"op": "region.move",  "id": reg0, "dx_cm": 4.0, "dy_cm": 0.0},    # ② revert
        {"op": "text.string",  "id": "t0", "value": original_str},         # ✓ accept (repair)
        {"op": "vocab.gap", "bbox_cm": {"x": 0, "y": 0, "w": 2, "h": 2},
         "describe": "forma que não sei mapear"},                          # → fila
    ]
    _, q, log = run_gate(analysis, edits, measure)
    print(f"\n=== edit_gate demo — capa{n} (proponente FAKE, sem VLM) ===")
    print(f"(baseline com texto DANIFICADO p/ provar o reparo; string real = {original_str!r})")
    for e in log:
        print(f"  {e['verdict']:16} {e['op']:14} {e['info']}")
    print(f"final: score={q.get('score')}  text_match={q.get('text_match')}")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _demo(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
