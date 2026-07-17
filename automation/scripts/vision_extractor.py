#!/usr/bin/env python3
"""
vision_extractor.py — Cover image → Gemini Vision → TikZ macro.

Converts a reference image to a LuaLaTeX-ready TikZ cover macro via the
Gemini Vision API, then applies brand color enforcement, logo injection,
footer/watermark macros, and a brand preamble before writing the result to
styles/versatus-dynamic-cover.tex.

CLI usage:
    python vision_extractor.py <image.(png|jpg|jpeg|webp)> [output.tex]

Environment variables:
    GEMINI_API_KEY  (required)  Google AI Studio — https://aistudio.google.com/app/apikey
    GEMINI_MODEL    (optional)  Override model (default: auto-select with fallback chain)
"""

import json
import os
import re
import sys
import time
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────

_HERE        = Path(__file__).resolve().parent   # automation/scripts/
_AUTOMATION  = _HERE.parent                       # automation/
_PROJECT_ROOT = _AUTOMATION.parent                # project root
_PROMPT_PATH        = _AUTOMATION / "prompt" / "vision_prompt.txt"
_REFINE_HEADER_PATH = _AUTOMATION / "prompt" / "refine_header.txt"
_OUTPUT_DIR         = _AUTOMATION / "output"
_BRANDS_DIR         = _PROJECT_ROOT / "brands"
_DEFAULT_TEX        = _AUTOMATION.parent / "styles" / "versatus-dynamic-cover.tex"
_DEFAULT_RAW        = _OUTPUT_DIR / "canvas_last.tikz"

# ─── MIME map ─────────────────────────────────────────────────────────────────

_MIME_MAP: dict[str, str] = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".webp": "image/webp",
    ".gif":  "image/gif",
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _detect_mime(path: Path) -> str:
    mime = _MIME_MAP.get(path.suffix.lower())
    if not mime:
        raise ValueError(
            f"Formato nao suportado: '{path.suffix}'. "
            f"Suportados: {', '.join(_MIME_MAP)}"
        )
    return mime


def _load_prompt() -> str:
    if not _PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt nao encontrado: {_PROMPT_PATH}")
    return _PROMPT_PATH.read_text(encoding="utf-8")


# ─── Brand palette injection ───────────────────────────────────────────────────
#
# We never trust the VLM to type an exact hex code correctly. Instead, the
# VLM only chooses WHERE each brand color ROLE applies in the composition
# (semantic naming, e.g. \definecolor{accent_1}{HTML}{...}); the actual hex
# value is always rewritten deterministically in Python afterwards, by a
# plain dictionary lookup. No network calls, no extra packages, cannot hang.

_HEX_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")


def _load_brand(brand_name: str) -> dict:
    brand_dir  = _BRANDS_DIR / brand_name
    brand_json = brand_dir / "brand.json"
    if not brand_json.exists():
        raise FileNotFoundError(
            f"Brand '{brand_name}' nao encontrada. Esperado: {brand_json}"
        )
    data = json.loads(brand_json.read_text(encoding="utf-8"))

    bad = [
        f"{role}={hexval!r}"
        for role, hexval in data.get("colors", {}).items()
        if not _HEX_RE.match(str(hexval))
    ]
    if bad:
        raise ValueError(
            f"brand.json de '{brand_name}' tem cores invalidas/incompletas: "
            f"{', '.join(bad)}. Preencha com hex valido (#RRGGBB) em {brand_json}"
        )
    return data


def _build_color_instructions(brand_colors: "dict[str, str] | None") -> str:
    if not brand_colors:
        return (
            "   \\definecolor{c0}{HTML}{E63946}\n"
            "   % Pick colors freely based on the image. Name them c0, c1, c2, ..."
        )

    lines = [
        "   You MUST use ONLY the brand colors listed below — do not invent",
        "   or guess any other hex value. Declare each with EXACTLY this name",
        "   (reuse a role for multiple zones if the image has more zones than roles):",
        "",
    ]
    for role, hexval in brand_colors.items():
        clean = str(hexval).lstrip("#").upper()
        lines.append(f"   \\definecolor{{{role}}}{{HTML}}{{{clean}}}")
    lines.append("")
    lines.append(
        "   For each distinct color zone in the reference image, assign the "
        "closest-fitting role above by visual weight and contrast: the darkest "
        "or dominant background zone -> bg_primary or bg_secondary; the "
        "lightest/neutral zone -> light; vivid focal zones -> accent_1 / "
        "accent_2; muted zones -> neutral or muted. Do NOT define any "
        "\\definecolor outside this exact list of names."
    )
    return "\n".join(lines)


def _enforce_brand_colors(
    block:        str,
    brand_colors: "dict[str, str]",
) -> "tuple[str, list[str]]":
    """
    Deterministically rewrites every \\definecolor{ROLE}{HTML}{xxxxxx} so that
    ROLE's hex always equals the brand's exact value, regardless of what hex
    the VLM actually typed. Pure regex substitution — no LLM call involved,
    cannot fail/hang. Returns (rewritten_block, names_outside_the_brand_palette).
    """
    off_palette: list[str] = []
    pattern = re.compile(r"\\definecolor\{([A-Za-z0-9_]+)\}\{HTML\}\{([0-9A-Fa-f]{3,8})\}")

    def _repl(m: "re.Match[str]") -> str:
        name = m.group(1)
        brand_hex = brand_colors.get(name)
        if brand_hex is None:
            off_palette.append(name)
            return m.group(0)
        clean = str(brand_hex).lstrip("#").upper()
        return f"\\definecolor{{{name}}}{{HTML}}{{{clean}}}"

    rewritten = pattern.sub(_repl, block)
    return rewritten, off_palette


# ─── Brand preamble (font + color aliases) ───────────────────────────────────
#
# versatus-dynamic-cover.tex is \input'd in the LaTeX PREAMBLE (before
# \begin{document}), so \setmainfont and \definecolor are valid there.
# We redefine the VS* color names that versatus-covers.sty uses, mapping
# them to the brand's exact hex values — no changes to any .sty file needed.

# VS color names (versatus-covers.sty) → brand.json role keys
_VS_TO_BRAND_ROLE: "dict[str, str]" = {
    "VSBlack":      "bg_primary",
    "VSGraphite":   "bg_secondary",
    "VSTeal":       "accent_1",
    "VSRed":        "accent_2",
    "VSSilver":     "neutral",
    "VSPaperWhite": "light",
    "VSMutedText":  "muted",
}


def _build_brand_preamble(
    brand_name:      str,
    brand_data:      dict,
    brand_colors:    "dict[str, str]",
    bg_hex_override: "str | None" = None,
) -> str:
    """
    Returns a LaTeX snippet to prepend to versatus-dynamic-cover.tex that:
      1. Overrides the document font with the brand's preferred typeface
         (with Noto Sans / Latin Modern Sans as safe fallbacks).
      2. Redefines the VS* color names used in versatus-covers.sty to the
         brand's exact hex values, so the text overlay inherits brand colors
         automatically without any changes to existing .sty files.
    """
    company = brand_data.get("company", brand_name)
    font    = brand_data.get("font", "Noto Sans")

    # Font override: brand font → Noto Sans → Latin Modern Sans
    _lm = r"\setmainfont{Latin Modern Sans}\setsansfont{Latin Modern Sans}"
    if font in ("Noto Sans", "Latin Modern Sans"):
        font_block = (
            f"\\IfFontExistsTF{{{font}}}{{"
            f"\\setmainfont{{{font}}}\\setsansfont{{{font}}}"
            f"}}{{{_lm}}}"
        )
    else:
        font_block = (
            f"\\IfFontExistsTF{{{font}}}{{\n"
            f"  \\setmainfont{{{font}}}\\setsansfont{{{font}}}%\n"
            f"}}{{\\IfFontExistsTF{{Noto Sans}}{{\n"
            f"  \\setmainfont{{Noto Sans}}\\setsansfont{{Noto Sans}}%\n"
            f"}}{{{_lm}}}}}"
        )

    # Color aliases: redefine VS* names to brand hex values
    bg_primary_hex = brand_colors.get("bg_primary", "")
    resolved: "dict[str, str]" = {
        vs_name: str(brand_colors.get(role, "")).lstrip("#").upper()
        for vs_name, role in _VS_TO_BRAND_ROLE.items()
        if brand_colors.get(role, "")
    }

    # VSRed (= accent_2) is also used as linkcolor on white paper.
    # Same-hue brands (accent_2 ≈ bg_primary) fall back to muted
    # (mid-gray, ~4.7:1 on white) rather than light (invisible on paper).
    if "VSRed" in resolved and bg_primary_hex:
        if _contrast_ratio(resolved["VSRed"], bg_primary_hex) < 2.5:
            resolved["VSRed"] = str(
                brand_colors.get("muted", "#5D5956")
            ).lstrip("#").upper()

    color_lines = [
        f"\\definecolor{{{vs_name}}}{{HTML}}{{{hexval}}}"
        for vs_name, hexval in resolved.items()
    ]

    # Dynamic foreground colors — use the ACTUAL generated background when available
    # (the VLM may use `light` or another role rather than `bg_primary`).
    # bg_hex_override is detected by scanning the first fill in the TikZ block.
    # Threshold 0.35 mirrors the logo variant selection (L < 0.35 = dark bg).
    effective_bg_hex = (bg_hex_override or bg_primary_hex or "").strip("#")
    bg_lum      = _luminance(effective_bg_hex) if effective_bg_hex else 0.1
    light_hex   = str(brand_colors.get("light", "#FFFFFF")).lstrip("#").upper()
    muted_hex   = str(brand_colors.get("muted", "#757576")).lstrip("#").upper()

    if bg_lum < 0.35:   # dark / vivid background → light text
        cover_fg       = light_hex
        cover_sub_fg   = _blend_hex(light_hex, "000000", 0.14)  # 86% light
        cover_muted_fg = _blend_hex(light_hex, "000000", 0.28)  # 72% light
        cover_faint_fg = _blend_hex(light_hex, "000000", 0.45)  # 55% light
    else:               # light background → dark text
        cover_fg       = "1A1A1A"
        cover_sub_fg   = muted_hex
        cover_muted_fg = muted_hex
        cover_faint_fg = muted_hex

    fg_lines = [
        f"\\definecolor{{VSCoverFg}}{{HTML}}{{{cover_fg}}}",
        f"\\definecolor{{VSCoverSubFg}}{{HTML}}{{{cover_sub_fg}}}",
        f"\\definecolor{{VSCoverMutedFg}}{{HTML}}{{{cover_muted_fg}}}",
        f"\\definecolor{{VSCoverFaintFg}}{{HTML}}{{{cover_faint_fg}}}",
    ]

    # Series name — brand-specific, overrides the generic default in metadata.tex
    series       = brand_data.get("series", "")
    series_lines = [f"\\renewcommand{{\\BookSeries}}{{{series}}}"] if series else []

    parts = [
        f"% === Brand preamble: {company} ===",
        font_block,
    ] + color_lines + fg_lines + series_lines + [
        "% === end brand preamble ===",
    ]
    return "\n".join(parts) + "\n"


# ─── Logo intelligence ────────────────────────────────────────────────────────
#
# After the background geometry is generated and brand colors are enforced,
# we measure the WCAG relative luminance of bg_primary to decide which logo
# variant looks best: light logo on dark bg, dark logo on light bg, alt otherwise.
# The selected logo .tikz file (pre-converted by convert_logos.py) is inlined
# directly into versatus-dynamic-cover.tex so no fragile \input path is needed.

def _srgb_linearize(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    """WCAG 2.1 relative luminance (0 = black, 1 = white)."""
    h = str(hex_color).lstrip("#")
    r = int(h[0:2], 16) / 255
    g = int(h[2:4], 16) / 255
    b = int(h[4:6], 16) / 255
    return (
        0.2126 * _srgb_linearize(r)
        + 0.7152 * _srgb_linearize(g)
        + 0.0722 * _srgb_linearize(b)
    )


def _contrast_ratio(hex1: str, hex2: str) -> float:
    """WCAG 2.1 contrast ratio between two hex colors (1.0–21.0)."""
    l1 = _luminance(hex1)
    l2 = _luminance(hex2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _blend_hex(base: str, toward: str, toward_factor: float) -> str:
    """Blend base hex color toward another hex color by a factor (0=pure base, 1=pure toward)."""
    b = str(base).lstrip("#")
    t = str(toward).lstrip("#")
    r = round(int(b[0:2], 16) * (1 - toward_factor) + int(t[0:2], 16) * toward_factor)
    g = round(int(b[2:4], 16) * (1 - toward_factor) + int(t[2:4], 16) * toward_factor)
    v = round(int(b[4:6], 16) * (1 - toward_factor) + int(t[4:6], 16) * toward_factor)
    return f"{r:02X}{g:02X}{v:02X}"


def _pascal(s: str) -> str:
    return "".join(w.capitalize() for w in s.replace("-", "_").split("_"))


def _choose_logo_variant(bg_primary_hex: str, available: "set[str]") -> str:
    """
    Brand convention (matches brand.json keys):
      'dark'  = logo designed for DARK backgrounds (light/white colors)
      'light' = logo designed for LIGHT backgrounds (dark colors)
      'alt'   = symbol/icon, works on mid-tone or as fallback

    luminance < 0.35  → dark background  → 'dark' variant
    luminance > 0.60  → light background → 'light' variant
    in-between        → 'alt' or 'dark' as fallback
    """
    lum = _luminance(bg_primary_hex)
    if lum < 0.35:
        preference = ["dark", "alt", "light"]
    elif lum > 0.60:
        preference = ["light", "alt", "dark"]
    else:
        preference = ["alt", "dark", "light"]
    for v in preference:
        if v in available:
            return v
    return next(iter(available), "dark")


def _inline_logo(
    brand_dir: Path,
    brand_data: dict,
    variant: str,
    brand_name: str,
) -> "tuple[str, str]":
    """
    Read the pre-converted logo .tikz file and return (content, macro_name).
    If the file is missing, returns a comment placeholder so the .tex stays
    syntactically valid and the caller can warn the user.
    """
    logos_map  = brand_data.get("logos", {})
    macro_name = f"Logo{_pascal(brand_name)}{_pascal(variant)}"
    rel        = logos_map.get(variant)

    if not rel:
        return (
            f"% [logo] brand.json nao define logos.{variant} — "
            f"verifique brands/{brand_name}/brand.json\n",
            "",
        )

    tikz_path = brand_dir / rel
    if not tikz_path.exists():
        return (
            f"% [logo] arquivo nao encontrado: {tikz_path.relative_to(brand_dir.parent)}\n"
            f"% Execute: python automation/scripts/convert_logos.py --brand {brand_name}\n",
            "",
        )

    return tikz_path.read_text(encoding="utf-8"), macro_name


# ─── Gemini Vision call ───────────────────────────────────────────────────────

# Fallback chain: most capable → most available
_GEMINI_CHAIN = [
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]


def _resolve_model_chain() -> "list[str]":
    """Return the model list to try, from GEMINI_MODEL env var or the default chain."""
    env = os.environ.get("GEMINI_MODEL", "").strip()
    if env.startswith("models/"):
        env = env[len("models/"):]
    return [env] if env else _GEMINI_CHAIN


def _call_gemini(parts, system_prompt: str, model: str, client) -> str:
    """
    Core Gemini call with 503-overload retry (shared by all callers).
    `parts` is a list of types.Part objects constructed by the caller.
    Raises RuntimeError on unrecoverable failures.
    """
    from google.genai import types  # noqa: PLC0415

    _BACKOFF = [10, 20]

    for _try in range(len(_BACKOFF) + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.1,
                    max_output_tokens=32768,
                ),
            )
            try:
                return response.text
            except (AttributeError, ValueError) as exc:
                candidates = getattr(response, "candidates", [])
                if candidates:
                    _parts = getattr(candidates[0].content, "parts", [])
                    if _parts:
                        return _parts[0].text
                finish = (
                    getattr(candidates[0], "finish_reason", "DESCONHECIDO")
                    if candidates else "SEM_CANDIDATOS"
                )
                raise RuntimeError(
                    f"Modelo sem texto (finish_reason={finish})."
                ) from exc

        except Exception as _exc:
            _s       = str(_exc)
            _is_busy = "503" in _s or "UNAVAILABLE" in _s or "overloaded" in _s.lower()
            if _is_busy and _try < len(_BACKOFF):
                _w = _BACKOFF[_try]
                print(f"    [!] {model}: sobrecarregado — aguardando {_w}s…")
                time.sleep(_w)
            else:
                raise

    raise RuntimeError(f"{model}: falhou apos {len(_BACKOFF)+1} tentativas.")


def _call_gemini_single(image_bytes: bytes, mime: str,
                        system_prompt: str, model: str, client,
                        pre_analysis: str = "") -> str:
    """Single-image Gemini call (initial cover generation)."""
    from google.genai import types  # noqa: PLC0415
    instruction = "Analyze this cover image and output the TikZ code as instructed."
    user_text   = f"{pre_analysis}\n\n{instruction}" if pre_analysis else instruction
    parts = [
        types.Part(inline_data=types.Blob(data=image_bytes, mime_type=mime)),
        types.Part(text=user_text),
    ]
    return _call_gemini(parts, system_prompt, model, client)


# ─── CV pre-render analysis ───────────────────────────────────────────────────

def _run_cv_analysis(image_path: Path) -> "dict | None":
    """
    Run CV pre-render analysis via image_analyzer (same directory).
    Returns None silently when the module or its dependencies are missing.
    """
    try:
        import importlib.util as _ilu  # noqa: PLC0415
        _spec = _ilu.spec_from_file_location(
            "image_analyzer", Path(__file__).parent / "image_analyzer.py"
        )
        if _spec is None:
            return None
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod.analyze_image(image_path)
    except Exception as exc:
        _s = str(exc)
        if "No module named" in _s or "ModuleNotFoundError" in type(exc).__name__:
            return None  # missing deps — silent skip
        print(f"    [CV] Aviso: analise falhou ({type(exc).__name__}: {_s[:80]})")
        return None


def _build_replicate_color_instructions(cv_colors: list[dict]) -> str:
    """Color instructions for --replicate mode: use CV-detected hex values exactly."""
    lines = [
        "   REPLICATE MODE — use EXACTLY these colors detected from the image.",
        "   Do NOT invent other hex values. Name them c0, c1, c2, ... in coverage order:",
        "",
    ]
    for i, c in enumerate(cv_colors[:_N_REPLICATE_COLORS]):
        clean = c["hex"].lstrip("#").upper()
        lines.append(
            f"   \\definecolor{{c{i}}}{{HTML}}{{{clean}}}  "
            f"% {c['coverage'] * 100:.1f}% coverage"
        )
    lines += [
        "",
        "   Map c0–c7 to the geometric zones you see. Do NOT add \\definecolor outside this list.",
    ]
    return "\n".join(lines)


_N_REPLICATE_COLORS = 8


# ─── TikZ extraction ──────────────────────────────────────────────────────────

def _extract_tikz_block(text: str) -> tuple[str | None, str]:
    """
    Find \\newcommand{\\RenderDynamicCover}{...} in the VLM response.
    Returns (block, status) where status is one of:
      "ok"         — complete, balanced block found
      "truncated"  — marker found but closing brace never reached
      "not_found"  — marker not present in the response at all
    """
    # Strip markdown code fences anywhere in the text
    text = re.sub(r"```(?:latex|tex)?\s*", "", text)
    text = re.sub(r"```", "", text)

    marker = r"\newcommand{\RenderDynamicCover}"
    start  = text.find(marker)
    if start == -1:
        return None, "not_found"

    # Find the opening { of the body (skip whitespace and % comments)
    pos = start + len(marker)
    while pos < len(text) and text[pos] in " \t\n\r%":
        pos += 1
    if pos >= len(text) or text[pos] != "{":
        return None, "not_found"

    # Walk forward to find the matching closing brace
    depth = 0
    end   = -1
    for i in range(pos, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        return None, "truncated"

    return text[start:end], "ok"


# Mandatory \Book* content macros — all must appear in every generated cover.
_REQUIRED_MACROS = (
    r"\BookTitle",
    r"\BookSubtitle",
    r"\BookDescription",
    r"\BookAuthor",
    r"\BookDate",
    r"\BookVersion",
)


def _validate_tikz(block: str) -> list[str]:
    """
    Lightweight sanity checks on the extracted TikZ block.
    Returns list of warning strings (empty = all good).
    """
    warnings = []

    if r"\begin{tikzpicture}" not in block:
        warnings.append("AVISO: \\begin{tikzpicture} ausente.")
    if r"\end{tikzpicture}" not in block:
        warnings.append("AVISO: \\end{tikzpicture} ausente.")

    # Check % LOGO_PLACEMENT comment
    if "% LOGO_PLACEMENT" not in block:
        warnings.append(
            "AVISO: % LOGO_PLACEMENT ausente — logo sera posicionado pelo "
            "brand.json, ignorando a imagem de referencia."
        )
    else:
        # Check that bg=ROLE matches one of the declared \definecolor names
        m = re.search(r"% LOGO_PLACEMENT.*?bg=([A-Za-z0-9_]+)", block)
        if m:
            bg_role  = m.group(1)
            declared = set(re.findall(r"\\definecolor\{([A-Za-z0-9_]+)\}", block))
            if declared and bg_role not in declared:
                warnings.append(
                    f"AVISO: LOGO_PLACEMENT bg={bg_role!r} nao corresponde a nenhum "
                    f"\\definecolor declarado. Roles disponiveis: {sorted(declared)}"
                )

    # Check all mandatory content macros
    missing = [m for m in _REQUIRED_MACROS if m not in block]
    if missing:
        warnings.append(
            f"AVISO: macros de conteudo ausentes: {', '.join(missing)}"
        )

    # Pixel-range numbers (anything over 150 is suspicious for an A4 cover in cm)
    # Exclude: hex color codes in \definecolor, arc degree angles (multiples of 90)
    _clean = re.sub(r"\\definecolor\{[^}]+\}\{HTML\}\{[0-9A-Fa-f]+\}", "", block)
    _clean = re.sub(r"arc\s*\([^)]*\)", "", _clean)
    numbers = re.findall(r"(?<![a-zA-Z{])(\d{3,}\.?\d*)", _clean)
    suspect = [n for n in numbers if float(n) > 150]
    if suspect:
        warnings.append(
            f"AVISO: valores numericos suspeitos (possivelmente pixels): "
            f"{suspect[:5]} — esperado range 0–30 cm."
        )

    return warnings


# ─── Refinement API call ─────────────────────────────────────────────────────

def _call_gemini_refine(ref_bytes: bytes, ref_mime: str, result_bytes: bytes,
                        system_prompt: str, model: str, client) -> str:
    """Two-image Gemini call (refinement pass: reference + current result)."""
    from google.genai import types  # noqa: PLC0415
    parts = [
        types.Part(inline_data=types.Blob(data=ref_bytes,    mime_type=ref_mime)),
        types.Part(inline_data=types.Blob(data=result_bytes, mime_type="image/png")),
        types.Part(text=(
            "Image 1 is the REFERENCE cover. "
            "Image 2 is the CURRENT RESULT. "
            "Output the corrected \\RenderDynamicCover as instructed."
        )),
    ]
    return _call_gemini(parts, system_prompt, model, client)


# ─── Post-extraction helpers ─────────────────────────────────────────────────

def _detect_bg_from_tikz(block: str, brand_colors: "dict[str, str]") -> str:
    """
    Scan the TikZ block for the first \fill[ROLE] rectangle command and
    return the brand hex for that role. This detects the ACTUAL background
    color used by the VLM (which may differ from brand.json's bg_primary).
    Returns hex string without '#', or "" if nothing found.
    """
    pat = re.compile(
        r"\\fill\[([A-Za-z0-9_]+)\]\s*\([^)]+\)\s*rectangle\s*\([^)]+\)"
    )
    for m in pat.finditer(block):
        role = m.group(1)
        if role in brand_colors:
            return str(brand_colors[role]).lstrip("#")
    return ""


def _parse_logo_placement(block: str) -> "dict | None":
    """
    Extract % LOGO_PLACEMENT x=X y=Y height=H bg=ROLE from TikZ block.
    Returns dict with keys x, y (float), height (float), bg (str), or None.
    """
    m = re.search(
        r"%\s*LOGO_PLACEMENT\s+"
        r"x=([0-9]+\.?[0-9]*)\s+"
        r"y=([0-9]+\.?[0-9]*)\s+"
        r"height=([0-9]+\.?[0-9]*)\s+"
        r"bg=([A-Za-z0-9_]+)",
        block,
    )
    if not m:
        return None
    return {
        "x":      float(m.group(1)),
        "y":      float(m.group(2)),
        "height": float(m.group(3)),
        "bg":     m.group(4),
    }


# ─── Shared finalization (used by extract_tikz + refine_tikz) ───────────────

def _resolve_brand(brand: "str | None") -> "tuple[dict, dict[str, str] | None]":
    """Load brand data and color map; returns ({}, None) when brand is None."""
    if not brand:
        return {}, None
    data = _load_brand(brand)
    return data, data.get("colors", {})


def _write_tex(
    tex_path:      "Path",
    comment:       str,
    brand_preamble: str,
    logo_inline:   str,
    block:         str,
) -> None:
    """Write the composed cover .tex to disk."""
    header = f"% {comment} - DO NOT EDIT MANUALLY\n"
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    tex_path.write_text(
        header + brand_preamble + logo_inline + block + "\n",
        encoding="utf-8",
    )


def _finalize_block(
    block:        str,
    brand:        "str | None",
    brand_data:   dict,
    brand_colors: "dict[str, str] | None",
) -> "tuple[str, str, str]":
    """
    Apply all post-extraction steps to a raw TikZ block:
      1. Enforce brand color hex values deterministically
      2. Inject logo + footer/watermark macros (dynamic variant + LOGO_PLACEMENT)
      3. Build brand preamble (font + VSCover* fg colors from actual background)

    Returns
    -------
    (brand_preamble, logo_inline, modified_block)
        Caller is responsible for writing to disk via _write_tex().
    """
    # ── 1. Brand color enforcement ────────────────────────────────────────────
    if brand_colors:
        block, off_palette = _enforce_brand_colors(block, brand_colors)
        if off_palette:
            print(f"    [!] Cores fora da paleta (mantidas): {sorted(set(off_palette))}")
        else:
            print(f"    [OK] Todas as cores forcadas para a paleta de '{brand}'.")

    # ── 2. Logo — dynamic variant, position, and scale ────────────────────────
    logo_inline = ""
    if brand and brand_colors:
        brand_dir_path = _BRANDS_DIR / brand
        available      = set(brand_data.get("logos", {}).keys())

        placement = _parse_logo_placement(block)
        if placement:
            pos            = [placement["x"], placement["y"]]
            logo_bg_hex    = str(
                brand_colors.get(placement["bg"],
                                 brand_colors.get("bg_primary", "#808080"))
            ).lstrip("#")
            desired_height = placement["height"]
            print(
                f"    [logo] LOGO_PLACEMENT: pos=({pos[0]}, {pos[1]}), "
                f"height={desired_height}cm, bg={placement['bg']}"
            )
        else:
            pos            = brand_data.get("logo_position", [1.5, 26.5])
            logo_bg_hex    = str(brand_colors.get("bg_primary", "#808080")).lstrip("#")
            desired_height = None
            print("    [!] [logo] LOGO_PLACEMENT ausente — usando logo_position do brand.json")

        variant            = _choose_logo_variant(logo_bg_hex, available)
        logo_inline, macro = _inline_logo(brand_dir_path, brand_data, variant, brand)

        if macro:
            native_height = float(brand_data.get("logo_height_cm", 3.0))
            scale         = (desired_height / native_height) if desired_height else 1.0
            lum           = _luminance(logo_bg_hex)
            end_marker    = "\\end{tikzpicture}%"

            if end_marker in block:
                if abs(scale - 1.0) > 0.005:
                    logo_call = (
                        f"  \\begin{{scope}}[shift={{({pos[0]}, {pos[1]})}}, "
                        f"xscale={scale:.4f}, yscale={scale:.4f}]\n"
                        f"    \\{macro}{{(0,0)}}\n"
                        f"  \\end{{scope}}"
                    )
                else:
                    logo_call = f"  \\{macro}{{({pos[0]}, {pos[1]})}}"
                block = block.replace(end_marker, logo_call + "\n" + end_marker, 1)
                print(
                    f"    [logo] variante='{variant}' (lum={lum:.3f}), "
                    f"scale={scale:.3f} -> \\{macro}"
                )
            else:
                print("    [!] [logo] \\end{tikzpicture}% nao encontrado no bloco.")
        else:
            print(f"    [!] [logo] {logo_inline.strip()}")

        # ── 2b. Footer logo + watermark macro definitions ─────────────────────
        # Prefer 'alt' (symbol) for footer, 'dark' for watermark; fall back to
        # the cover variant when the preferred one is absent.
        footer_variant = "alt"  if "alt"  in available else variant
        wm_variant     = "dark" if "dark" in available else variant
        extra_logos    = ""
        # Only generate macros for variants whose .tikz file was actually found
        actually_have  = {variant} if macro else set()

        for vname in dict.fromkeys([footer_variant, wm_variant]):
            if vname not in actually_have and vname in available:
                extra_c, extra_m = _inline_logo(brand_dir_path, brand_data, vname, brand)
                if extra_m:
                    extra_logos += extra_c
                    actually_have.add(vname)

        fmacro = (
            f"Logo{_pascal(brand)}{_pascal(footer_variant)}"
            if footer_variant in actually_have else ""
        )
        wmacro = (
            f"Logo{_pascal(brand)}{_pascal(wm_variant)}"
            if wm_variant in actually_have else ""
        )

        if fmacro:
            extra_logos += (
                "\\renewcommand{\\VSBrandFooterLogo}{%\n"
                "  \\resizebox{!}{0.50cm}{%\n"
                "    \\begin{tikzpicture}[baseline=(current bounding box.south)]%\n"
                f"      \\{fmacro}{{(0,0)}}%\n"
                "    \\end{tikzpicture}%\n"
                "  }%\n"
                "}\n"
            )

        if wmacro:
            extra_logos += (
                "\\renewcommand{\\VSBrandWatermark}{%\n"
                "  \\ifVSWatermark\n"
                "  \\begin{tikzpicture}[remember picture, overlay]%\n"
                "    \\node[opacity=0.030, anchor=center, inner sep=0pt]\n"
                "      at (current page.center)\n"
                "      {\\resizebox{12cm}{!}{%\n"
                "        \\begin{tikzpicture}%\n"
                f"          \\{wmacro}{{(0,0)}}%\n"
                "        \\end{tikzpicture}%\n"
                "      }};\n"
                "  \\end{tikzpicture}%\n"
                "  \\fi\n"
                "}\n"
            )

        if extra_logos:
            logo_inline = logo_inline + extra_logos
            print(
                f"    [layout] \\VSBrandFooterLogo -> \\{fmacro or '(none)'}  |  "
                f"\\VSBrandWatermark -> \\{wmacro or '(none)'}"
            )

    # ── 3. Brand preamble — font + fg colors from actual bg ──────────────────
    brand_preamble = ""
    if brand and brand_colors:
        bg_hex_actual  = _detect_bg_from_tikz(block, brand_colors)
        brand_preamble = _build_brand_preamble(
            brand, brand_data, brand_colors,
            bg_hex_override=bg_hex_actual or None,
        )
        print(
            f"    [font] {brand_data.get('font', 'N/A')} "
            f"(com fallback Noto Sans / Latin Modern Sans)"
        )
        if bg_hex_actual:
            bg_lum = _luminance(bg_hex_actual)
            mode   = "escuro→texto claro" if bg_lum < 0.35 else "claro→texto escuro"
            print(f"    [fg-color] bg detectado: #{bg_hex_actual} (L={bg_lum:.3f}, {mode})")

    return brand_preamble, logo_inline, block


# ─── Public API ───────────────────────────────────────────────────────────────

def extract_tikz(
    image_path:  "str | Path",
    output_tex:  "str | Path | None" = None,
    brand:       "str | None" = None,
    replicate:   bool = False,
) -> Path:
    """
    Run the full pipeline: image → CV analysis → Gemini Vision → TikZ macro.

    Parameters
    ----------
    image_path : str or Path
        Path to the cover image (PNG / JPEG / WEBP).
    output_tex : str, Path, or None
        Destination .tex file. Default: styles/versatus-dynamic-cover.tex
    brand : str or None
        Brand name under brands/<brand>/brand.json. When given, the VLM is
        instructed to use ONLY that brand's color roles, and the resulting
        hex values are deterministically forced to the brand's exact colors
        afterwards (see _enforce_brand_colors) — no LLM hallucination risk.
    replicate : bool
        When True, skip all brand logic. Colors come from CV analysis (exact
        K-means hex); no logo injection; no brand preamble. Useful for
        faithfully replicating a third-party cover without brand transformation.

    Returns
    -------
    Path
        Path of the written .tex file.

    Raises
    ------
    FileNotFoundError       Image, prompt, or brand.json not found.
    EnvironmentError        GEMINI_API_KEY not set.
    ValueError              Could not extract \\RenderDynamicCover from response.
    RuntimeError            All Gemini models failed.
    """
    try:
        from google import genai
    except ImportError as exc:
        raise ImportError(
            "Pacote google-genai nao instalado. Execute: pip install google-genai"
        ) from exc

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY nao esta definida.\n"
            "Obtenha uma chave gratuita em: https://aistudio.google.com/app/apikey\n"
            "Depois execute:  set GEMINI_API_KEY=sua_chave  (Windows)"
        )

    image_path = Path(image_path).resolve()
    tex_path   = Path(output_tex).resolve() if output_tex else _DEFAULT_TEX

    if not image_path.exists():
        raise FileNotFoundError(f"Imagem nao encontrada: {image_path}")

    # ── 1. CV pre-render analysis (always runs; silent if deps missing) ────────
    print("[1/4] Analise CV da imagem…")
    cv_data    = _run_cv_analysis(image_path)
    cv_summary = cv_data.get("summary_text", "") if cv_data else ""
    if cv_data and cv_data.get("cv_available"):
        _nc = len(cv_data.get("colors", []))
        _nr = len(cv_data.get("regions", []))
        _lt = cv_data.get("layout", {}).get("layout_type", "unknown")
        print(f"    CV     : {_nc} cores, {_nr} regioes, layout={_lt}")
    else:
        print("    CV     : indisponivel (numpy/sklearn/skimage ausentes) — continuando sem pre-analise")

    # ── 2. Prompt ─────────────────────────────────────────────────────────────
    print("[2/4] Carregando prompt de visao…")
    system_prompt = _load_prompt()

    if replicate:
        # Replicate mode: colors from CV measurement, no brand transformation
        brand_data, brand_colors = {}, None
        if cv_data and cv_data.get("colors"):
            color_block = _build_replicate_color_instructions(cv_data["colors"])
        else:
            color_block = (
                "   REPLICATE MODE — pick colors freely from the image.\n"
                "   Name them c0, c1, c2, ... in descending coverage order."
            )
        print("    Modo   : REPLICATE (sem brand, cores do CV)")
    else:
        brand_data, brand_colors = _resolve_brand(brand)
        if brand:
            print(f"    Brand  : {brand_data.get('company', brand)} ({len(brand_colors)} cores)")
        color_block = _build_color_instructions(brand_colors)

    system_prompt = system_prompt.replace("{{COLOR_INSTRUCTIONS}}", color_block)
    print(f"    Prompt : {_PROMPT_PATH.name} ({len(system_prompt)} chars)")

    # ── 3. Vision API — itera modelos ate obter bloco TikZ completo ───────────
    print("[3/4] Chamando Gemini Vision…")
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    model_chain = _resolve_model_chain()
    mime        = _detect_mime(image_path)
    image_bytes = image_path.read_bytes()
    print(f"    Imagem : {image_path.name} ({len(image_bytes) / 1024:.1f} KB)")

    client      = genai.Client(http_options={"api_version": "v1beta"})
    block       = None
    last_raw    = ""
    last_status = "not_found"

    for _model in model_chain:
        print(f"    Modelo : {_model}")
        try:
            raw_text = _call_gemini_single(
                image_bytes, mime, system_prompt, _model, client,
                pre_analysis=cv_summary,
            )
        except Exception as exc:
            _s       = str(exc)
            _is_busy = "503" in _s or "UNAVAILABLE" in _s or "overloaded" in _s.lower()
            _is_rate = "429" in _s or "quota" in _s.lower() or "RESOURCE_EXHAUSTED" in _s
            _is_miss = "404" in _s or "NOT_FOUND" in _s
            _is_auth = "401" in _s or "authentication" in _s.lower() or "invalid api key" in _s.lower()
            if _is_auth:
                raise  # bad key — no point trying other models
            if _is_busy or _is_rate or _is_miss:
                reason = ("sobrecarregado" if _is_busy
                          else "cota excedida" if _is_rate
                          else "nao disponivel")
                print(f"    [!] {_model}: {reason} — tentando proximo…")
                continue
            raise  # unexpected error → stop

        if not raw_text:
            print(f"    [!] {_model}: resposta vazia — tentando proximo…")
            continue

        print(f"    Resposta : {len(raw_text)} chars")
        last_raw = raw_text
        _DEFAULT_RAW.write_text(raw_text, encoding="utf-8")

        block, last_status = _extract_tikz_block(raw_text)

        if last_status == "ok":
            print(f"    [OK] Bloco TikZ completo ({len(block)} chars).")
            break
        elif last_status == "truncated":
            print(
                f"    [!] {_model}: resposta truncada ({len(raw_text)} chars) "
                f"— tentando proximo modelo…"
            )
            block = None
        else:
            print(
                f"    [!] {_model}: \\RenderDynamicCover nao encontrado "
                f"— tentando proximo modelo…"
            )
            block = None

    if block is None:
        err_path = _DEFAULT_RAW.with_suffix(".error.txt")
        err_path.write_text(last_raw, encoding="utf-8")
        detail = (
            "resposta truncada — o modelo parou antes de fechar o bloco TikZ"
            if last_status == "truncated"
            else "\\newcommand{\\RenderDynamicCover} ausente na resposta"
        )
        raise ValueError(
            f"Todos os modelos falharam: {detail}.\n"
            f"Ultima resposta salva em: {err_path}\n"
            f"Primeiros 400 chars: {last_raw[:400]!r}"
        )

    # ── 4. Finalize: enforce colors, inject logo, build preamble ─────────────
    # In replicate mode we pass brand=None so _finalize_block skips logo and
    # brand preamble — the output is a pure color-faithful TikZ replication.
    _brand_for_finalize = None if replicate else brand
    brand_preamble, logo_inline, block = _finalize_block(
        block, _brand_for_finalize, brand_data, brand_colors
    )

    # ── 5. Validate + write ───────────────────────────────────────────────────
    print("[4/4] Validando e escrevendo macro TikZ…")
    for warning in _validate_tikz(block):
        print(f"    {warning}")

    if replicate:
        tex_comment = "Replicated by vision_extractor.py (CV colors, no brand)"
    else:
        brand_note  = f" (brand: {brand})" if brand else ""
        tex_comment = f"Auto-generated by vision_extractor.py{brand_note}"
    _write_tex(tex_path, tex_comment, brand_preamble, logo_inline, block)
    print(f"    Macro TikZ escrita → {tex_path}")

    return tex_path


def reuse_tikz(
    output_tex: "str | Path | None" = None,
    brand:      "str | None"        = None,
) -> Path:
    """
    Rebuild versatus-dynamic-cover.tex from the cached canvas_last.tikz
    WITHOUT calling the Gemini API.

    Re-applies brand enforcement, logo injection, and brand preamble from
    scratch — useful when brand.json changed (logo size, position, color)
    and you want to recompile without paying an API call.

    Raises
    ------
    FileNotFoundError  if canvas_last.tikz does not exist yet
    ValueError         if the cached file has no valid \\RenderDynamicCover block
    """
    if not _DEFAULT_RAW.exists():
        raise FileNotFoundError(
            f"Cache nao encontrado: {_DEFAULT_RAW}\n"
            f"Execute o pipeline completo ao menos uma vez antes de usar --reuse."
        )

    tex_path = Path(output_tex).resolve() if output_tex else _DEFAULT_TEX

    print(f"[REUSE] Carregando TikZ em cache: {_DEFAULT_RAW.name}")
    raw = _DEFAULT_RAW.read_text(encoding="utf-8")

    block, status = _extract_tikz_block(raw)
    if status != "ok":
        detail = (
            "bloco truncado no cache" if status == "truncated"
            else "\\newcommand{\\RenderDynamicCover} ausente no cache"
        )
        raise ValueError(
            f"Cache invalido: {detail}.\n"
            f"Delete {_DEFAULT_RAW} e rode o pipeline completo novamente."
        )

    print(f"[REUSE] Bloco extraido ({len(block)} chars). Reaplicando brand…")

    brand_data, brand_colors = _resolve_brand(brand)
    if brand:
        print(f"    Brand: {brand_data.get('company', brand)}")

    brand_preamble, logo_inline, block = _finalize_block(
        block, brand, brand_data, brand_colors
    )

    _write_tex(tex_path, f"Rebuilt from cache by vision_extractor.reuse_tikz (brand: {brand})",
               brand_preamble, logo_inline, block)
    print(f"[REUSE] Macro TikZ escrita → {tex_path}")
    return tex_path


def refine_tikz(
    reference_image: "str | Path",
    result_png:      "str | Path",
    output_tex:      "str | Path | None" = None,
    brand:           "str | None"        = None,
) -> Path:
    """
    Second-pass refinement: compare reference image + compiled result PNG,
    ask Gemini to produce a corrected \\RenderDynamicCover, then finalize
    (brand enforcement + logo + preamble) and overwrite the .tex file.

    Parameters
    ----------
    reference_image : original reference cover image sent to the first pass
    result_png      : PNG of the compiled cover (from preview_cover.render_pdf_page)
    output_tex      : destination .tex (default: styles/versatus-dynamic-cover.tex)
    brand           : brand name under brands/<brand>/brand.json

    Returns
    -------
    Path  — path of the written .tex file
    """
    try:
        from google import genai
    except ImportError as exc:
        raise ImportError("pip install google-genai") from exc

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY nao esta definida.\n"
            "Execute:  set GEMINI_API_KEY=sua_chave  (Windows)"
        )

    ref_path    = Path(reference_image).resolve()
    result_path = Path(result_png).resolve()
    tex_path    = Path(output_tex).resolve() if output_tex else _DEFAULT_TEX

    if not ref_path.exists():
        raise FileNotFoundError(f"Imagem de referencia nao encontrada: {ref_path}")
    if not result_path.exists():
        raise FileNotFoundError(f"PNG do resultado nao encontrado: {result_path}")

    # ── 1. Build system prompt: refine_header + vision rules ─────────────────
    print("[1/3] Carregando prompt de refinamento…")
    if not _REFINE_HEADER_PATH.exists():
        raise FileNotFoundError(f"refine_header.txt nao encontrado: {_REFINE_HEADER_PATH}")

    vision_rules   = _load_prompt()
    refine_header  = _REFINE_HEADER_PATH.read_text(encoding="utf-8")
    system_prompt  = refine_header + "\n\n" + vision_rules

    brand_data, brand_colors = _resolve_brand(brand)
    if brand:
        print(f"    Brand: {brand_data.get('company', brand)}")
    color_block   = _build_color_instructions(brand_colors)
    system_prompt = system_prompt.replace("{{COLOR_INSTRUCTIONS}}", color_block)
    print(f"    Prompt: {len(system_prompt)} chars")

    # ── 2. Vision API — two images (reference + result) ───────────────────────
    print("[2/3] Chamando Gemini Vision (refinamento com 2 imagens)…")
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    model_chain = _resolve_model_chain()

    ref_bytes    = ref_path.read_bytes()
    result_bytes = result_path.read_bytes()
    ref_mime     = _detect_mime(ref_path)
    print(f"    Ref   : {ref_path.name} ({len(ref_bytes)/1024:.1f} KB)")
    print(f"    Result: {result_path.name} ({len(result_bytes)/1024:.1f} KB)")

    client      = genai.Client(http_options={"api_version": "v1beta"})
    block       = None
    last_raw    = ""
    last_status = "not_found"

    for _model in model_chain:
        print(f"    Modelo: {_model}")
        try:
            raw_text = _call_gemini_refine(
                ref_bytes, ref_mime, result_bytes, system_prompt, _model, client
            )
        except Exception as exc:
            _s = str(exc)
            if "401" in _s or "authentication" in _s.lower():
                raise
            print(f"    [!] {_model}: {_s[:80]} — tentando proximo…")
            continue

        if not raw_text:
            print(f"    [!] {_model}: resposta vazia — tentando proximo…")
            continue

        print(f"    Resposta: {len(raw_text)} chars")
        last_raw = raw_text
        _DEFAULT_RAW.write_text(raw_text, encoding="utf-8")

        block, last_status = _extract_tikz_block(raw_text)

        if last_status == "ok":
            print(f"    [OK] Bloco TikZ refinado ({len(block)} chars).")
            break
        elif last_status == "truncated":
            print(f"    [!] {_model}: resposta truncada — tentando proximo…")
            block = None
        else:
            print(f"    [!] {_model}: \\RenderDynamicCover ausente — tentando proximo…")
            block = None

    if block is None:
        err_path = _DEFAULT_RAW.with_suffix(".refine_error.txt")
        err_path.write_text(last_raw, encoding="utf-8")
        raise ValueError(
            f"Refinamento falhou: bloco TikZ nao encontrado.\n"
            f"Ultima resposta salva em: {err_path}"
        )

    # ── 3. Finalize + write ───────────────────────────────────────────────────
    print("[3/3] Finalizando bloco refinado…")
    for warning in _validate_tikz(block):
        print(f"    {warning}")

    brand_preamble, logo_inline, block = _finalize_block(
        block, brand, brand_data, brand_colors
    )

    _write_tex(tex_path, f"Refined by vision_extractor.refine_tikz (brand: {brand})",
               brand_preamble, logo_inline, block)
    print(f"    Macro TikZ refinada → {tex_path}")
    return tex_path


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    usage = (
        f"Usage: python {Path(__file__).name} "
        "<imagem.(png|jpg|jpeg|webp)> [output.tex] [--brand NOME]\n\n"
        "Env var obrigatoria:\n"
        "  GEMINI_API_KEY  Chave do Google AI Studio\n\n"
        "Env var opcional:\n"
        "  GEMINI_MODEL    Modelo a usar (default: gemini-3-flash-preview)"
    )

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(usage)
        sys.exit(0)

    _argv = sys.argv[1:]
    _brand_arg = None
    if "--brand" in _argv:
        _i = _argv.index("--brand")
        _brand_arg = _argv[_i + 1] if _i + 1 < len(_argv) else None
        del _argv[_i:_i + 2]

    try:
        t = extract_tikz(
            _argv[0],
            _argv[1] if len(_argv) > 1 else None,
            brand=_brand_arg,
        )
        print(f"\n[DONE]  LaTeX macro → {t}")
        print(f"        TikZ bruto  → {_DEFAULT_RAW}")
    except EnvironmentError as exc:
        print(f"\n[CONFIG ERROR]\n{exc}", file=sys.stderr)
        sys.exit(2)
    except (ValueError, FileNotFoundError) as exc:
        print(f"\n[DATA ERROR]\n{exc}", file=sys.stderr)
        sys.exit(3)
    except Exception as exc:
        import traceback
        print(f"\n[ERRO] {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(4)
