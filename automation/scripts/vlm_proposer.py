#!/usr/bin/env python3
"""
vlm_proposer.py — the VLM as a PROPOSER of typed edits (Fase 5, peça 4).

The VLM never touches the project. It looks at the ORIGINAL cover, the current RENDER,
and the structured evidence we already have (analysis.json, palette, the zone error map),
and returns a list of TYPED EDITS against our schema. Those edits go straight into
`edit_gate.run_gate`, which grounds and MEASURES each one — so a hallucinated edit is
rejected exactly like the FAKE proposer's was. The VLM speaks only in `edit_gate`'s
vocabulary; the gate is the authority.

Determinism containment: the VLM emits DATA (edits), never code; each edit is gated;
its answer is cached in the analysis so a re-run is reproducible.

Provider: **Gemini** (the project already has it configured). Reuses the existing
`vision_extractor` plumbing — `google-genai` SDK, `GEMINI_API_KEY`, the model fallback
chain, and the 503-retry `_call_gemini` — WITHOUT modifying that out-of-scope module.
Needs `GEMINI_API_KEY` in the environment + `pip install google-genai`. Until then, pass
`mock=[...]` to exercise the whole path with NO API call:

    python automation/scripts/vlm_proposer.py 7      # MOCK demo (no key needed)
"""

import importlib.util
import json
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# The edit vocabulary, described for the VLM (kept in lockstep with edit_gate).
_SCHEMA_DOC = """\
Each edit is one JSON object. Allowed ops and fields (reference elements by their _id):
  {"op":"text.string",  "id":"t0", "value":"Control Unit"}     # fix a mis-read string
  {"op":"text.add",     "value":"Braun Audio\\nRegie 308",     # ADD text the OCR missed —
                        "bbox_cm":{"x":..,"y":..,"w":..,"h":..},#   you READ it, so inject it
                        "hex":"#FFFFFF"}                        #   (do NOT use vocab.gap for text)
  {"op":"text.move",    "id":"t0", "dx_cm":0.4, "dy_cm":-0.2}  # nudge text
  {"op":"text.hscale",  "id":"t0", "value":0.72}               # condense a wide font
  {"op":"region.color", "id":"r5", "hex":"#EF5623"}            # recolour (palette only)
  {"op":"region.move",  "id":"r5", "dx_cm":0.3, "dy_cm":0}
  {"op":"region.resize","id":"r5", "w_cm":5.1, "h_cm":5.1}
  {"op":"region.remove","id":"r8"}                             # drop a false shape
  {"op":"region.add",   "shape":"polygon", "hex":"#EF5623",
                        "points_cm":[[x,y],...]}               # a shape we're missing
  {"op":"region.add",   "shape":"hatch", "hex":"#000000",     # a PARALLEL-LINE hatch field:
                        "base_hex":"#E4342B", "bbox_cm":{..},  #   line colour + base colour,
                        "period_cm":0.15, "line_width_pt":1.0, #   line spacing (cm) + width,
                        "direction":"v"}                       #   'v'=vertical, 'h'=horizontal
  {"op":"logo.mark",    "name":"Braun",                        # a graphic brand LOGO → we show
                        "bbox_cm":{"x":..,"y":..,"w":..,"h":..},#   "Braun (Logo)" as a placeholder
                        "hex":"#FFFFFF"}                        #   (NEVER reconstruct/redraw it)
  {"op":"vocab.gap",    "bbox_cm":{"x":..,"y":..,"w":..,"h":..},
                        "describe":"a shape I can't map"}      # FLAG a missing primitive
Rules: colours MUST be near a palette colour; coordinates are in cm, TikZ y-up (0,0 =
bottom-left); a string must fit its box. Propose only edits you're confident improve the
render's fidelity to the ORIGINAL. Return ONLY JSON: {"edits":[...]} — no prose, no fences."""

_SYSTEM = (
    "You are a meticulous visual-diff reviewer for a deterministic cover replicator. "
    "You compare the ORIGINAL cover image against the current RENDER and propose small, "
    "TYPED EDITS to our structured description (analysis.json) that raise fidelity. You do "
    "NOT redraw or write code — you emit edits as data. Prefer the fewest edits that fix "
    "the biggest errors. Focus on the worst zones first. For TEXT the OCR missed, USE "
    "text.add (you can read it) — do not flag text as a gap. For a field of parallel lines "
    "USE region.add shape=hatch. For a graphic brand LOGO (a logomark like BRAUN, or the "
    "versatus 'v'), USE logo.mark with the brand NAME — NEVER reconstruct it, redraw its "
    "shapes, or add it as plain text; we render '<Name> (Logo)' as a placeholder and insert "
    "the real logo later. Reserve vocab.gap for patterns you STILL can't express (dense "
    "mosaics); never for text, hatching, or logos.\n\n" + _SCHEMA_DOC
)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _context_text(analysis: dict, zones: "list | None") -> str:
    """The structured evidence the VLM reasons over — palette, text, shapes, worst zones."""
    pal = ", ".join(c["hex"] for c in analysis.get("colors", [])[:8])
    texts = [{"_id": t.get("_id"), "text": t.get("text"), "bbox_cm": t.get("bbox_cm")}
             for t in analysis.get("text_elements", [])]
    shapes = [{"_id": r.get("_id"), "shape": r.get("shape_type"),
               "hex": r.get("color_hex"), "bbox_cm": r.get("bbox_cm")}
              for r in analysis.get("regions", [])]
    parts = [
        f"CANVAS (cm): {analysis.get('canvas')}",
        f"PALETTE: {pal}",
        f"TEXT ELEMENTS: {json.dumps(texts, ensure_ascii=False)}",
        f"SHAPES (first 40): {json.dumps(shapes[:40], ensure_ascii=False)}",
    ]
    if zones:
        worst = "; ".join(f"{z['loc']} content={z['cm']:.2f} err%={z['pct']:.0f}"
                          for z in zones[:6])
        parts.append(f"WORST ZONES (error x area, worst first): {worst}")
    return "\n".join(parts)


def _edits_from_text(text: str) -> list:
    """Parse the model's reply into an edits list, tolerating markdown fences/prose."""
    t = (text or "").strip()
    m = re.search(r"\{.*\}", t, re.DOTALL)   # grab the outermost JSON object
    if m:
        t = m.group(0)
    try:
        return json.loads(t).get("edits", [])
    except Exception:
        return []


def propose(
    analysis: dict, image_path: "str | Path", render_path: "str | Path",
    zones: "list | None" = None, mock: "list | None" = None, max_edits: int = 12,
) -> list:
    """Ask the VLM (or a mock) for a list of typed edits. Returns the edits list.

    `mock` short-circuits the API call — pass a list of edit dicts to test the pipeline
    with no key. Live path calls Gemini vision via the project's existing config."""
    if mock is not None:
        return mock[:max_edits]

    from google import genai            # noqa: PLC0415 — live path only
    from google.genai import types      # noqa: PLC0415
    ve = _load("vision_extractor")       # reuse _call_gemini + the model chain (no edits)

    client = genai.Client(http_options={"api_version": "v1beta"})   # reads GEMINI_API_KEY
    prompt = (_context_text(analysis, zones)
              + f"\n\nPropose at most {max_edits} edits. Return ONLY JSON: "
              '{"edits":[ ... ]}.')
    parts = [
        types.Part(text="ORIGINAL cover (the target):"),
        types.Part(inline_data=types.Blob(data=Path(image_path).read_bytes(),
                                           mime_type="image/png")),
        types.Part(text="Current RENDER (what we produced):"),
        types.Part(inline_data=types.Blob(data=Path(render_path).read_bytes(),
                                           mime_type="image/png")),
        types.Part(text=prompt),
    ]
    last = None
    for model in ve._resolve_model_chain():
        try:
            return _edits_from_text(ve._call_gemini(parts, _SYSTEM, model, client))[:max_edits]
        except Exception as exc:
            last = exc
    raise RuntimeError(f"todos os modelos Gemini falharam: {last}")


def zones_for(image_path: "str | Path", render_path: "str | Path") -> list:
    """Reuse zone_board to hand the VLM a worst-first error map (best-effort)."""
    try:
        import numpy as np
        from PIL import Image
        zb = _load("zone_board")
        orig = Image.open(image_path).convert("RGB")
        rend = Image.open(render_path).convert("RGB").resize(orig.size, Image.LANCZOS)
        cells = zb.zone_scores(np.asarray(orig), np.asarray(rend), 6, 4, zb._vc())
        total = sum(c["err"] for c in cells) or 1.0
        return [{"loc": f"r{c['i']}c{c['j']}", "cm": c["cm"], "pct": 100 * c["err"] / total}
                for c in sorted(cells, key=lambda c: -c["err"])]
    except Exception:
        return []


def _demo(n: int) -> None:
    """MOCK demo — proves propose() → gate wiring with NO API call."""
    eg = _load("edit_gate")
    analysis, measure, paths = eg.cover_measure(n)
    zones = zones_for(paths["img"], paths["cover_dir"] / "render.png")

    # Stand in for the VLM: a plausible fix + a hallucination + a gap. The gate decides.
    reg0 = analysis["regions"][0]["_id"]
    mock_edits = [
        {"op": "region.color", "id": reg0, "hex": "#00FF00"},          # hallucinated → ✗
        {"op": "region.move",  "id": reg0, "dx_cm": 5.0, "dy_cm": 0},  # bad move → ↩
        {"op": "vocab.gap", "bbox_cm": {"x": 0, "y": 0, "w": 2, "h": 2},
         "describe": "angular pie wedge I can't express"},             # → fila
    ]
    edits = propose(analysis, paths["img"], paths["render"], zones=zones, mock=mock_edits)
    print(f"\n=== vlm_proposer MOCK demo — capa{n} (proposer→gate, NO API) ===")
    if zones:
        print(f"pior zona p/ o VLM focar: {zones[0]['loc']} "
              f"(content {zones[0]['cm']:.2f}, {zones[0]['pct']:.0f}% do erro)")
    print(f"VLM propôs {len(edits)} edits → gatekeeper:")
    best, q, log = eg.run_gate(analysis, edits, measure)
    for e in log:
        print(f"  {e['verdict']:16} {e['op']:14} {e['info']}")
    n_gaps = eg.persist_vocab_gaps(best, f"capa_teste{n}")   # peça 5: a fila cresce
    print(f"vocab.gap persistidos p/ o dev: {n_gaps} → automation/output/vocab_gaps.jsonl")
    print("(com GEMINI_API_KEY setada, troque mock=... por propose() ao vivo)")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _demo(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
