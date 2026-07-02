#!/usr/bin/env python3
"""
vision_extractor.py — Cover image → Gemini Vision → TikZ macro.

Steps:
  1. Load system prompt from automation/prompt/vision_prompt.txt
  2. Send the image to Gemini Vision API
  3. Extract \\newcommand{\\RenderDynamicCover}{...} from the response
  4. Run lightweight validation (structure + sanity checks)
  5. Save raw response to automation/output/canvas_last.tikz  (for debugging)
  6. Write the TikZ macro to styles/versatus-dynamic-cover.tex

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
_PROMPT_PATH = _AUTOMATION / "prompt" / "vision_prompt.txt"
_OUTPUT_DIR  = _AUTOMATION / "output"
_BRANDS_DIR  = _PROJECT_ROOT / "brands"
_DEFAULT_TEX = _AUTOMATION.parent / "styles" / "versatus-dynamic-cover.tex"
_DEFAULT_RAW = _OUTPUT_DIR / "canvas_last.tikz"

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

# Brand color roles (brand.json keys) → VS color names (versatus-covers.sty)
_BRAND_ROLE_TO_VS: "dict[str, str]" = {
    "VSBlack":      "bg_primary",
    "VSGraphite":   "bg_secondary",
    "VSTeal":       "accent_1",
    "VSRed":        "accent_2",
    "VSSilver":     "neutral",
    "VSPaperWhite": "light",
    "VSMutedText":  "muted",
}


def _build_brand_preamble(
    brand_name:   str,
    brand_data:   dict,
    brand_colors: "dict[str, str]",
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
    color_lines: "list[str]" = []
    for vs_name, role in _BRAND_ROLE_TO_VS.items():
        hexval = brand_colors.get(role, "")
        if not hexval:
            continue
        # VSRed is used as the separator rule in the text overlay. If accent_2
        # has low contrast against bg_primary the separator becomes invisible,
        # so fall back to the brand's light color.
        if vs_name == "VSRed" and bg_primary_hex:
            cr = _contrast_ratio(hexval, bg_primary_hex)
            if cr < 2.5:
                hexval = brand_colors.get("light", "#FFFFFF")
        clean = str(hexval).lstrip("#").upper()
        color_lines.append(f"\\definecolor{{{vs_name}}}{{HTML}}{{{clean}}}")

    parts = [
        f"% === Brand preamble: {company} ===",
        font_block,
    ] + color_lines + [
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


def _call_gemini_single(
    image_path: Path,
    system_prompt: str,
    model: str,
    image_bytes: bytes,
    mime: str,
    client,
) -> str:
    """
    Call ONE Gemini model. Retries up to 2x on 503 overload.
    Raises RuntimeError/EnvironmentError on unrecoverable failures.
    """
    from google.genai import types  # noqa: PLC0415

    _BACKOFF = [10, 20]

    for _try in range(len(_BACKOFF) + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                inline_data=types.Blob(
                                    data=image_bytes, mime_type=mime
                                )
                            ),
                            types.Part(
                                text=(
                                    "Analyze this cover image and output "
                                    "the TikZ code as instructed."
                                )
                            ),
                        ],
                    )
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.1,
                    max_output_tokens=32768,
                ),
            )
            # Extract text safely (handles safety-filter blocks)
            try:
                return response.text
            except (AttributeError, ValueError) as exc:
                candidates = getattr(response, "candidates", [])
                if candidates:
                    parts = getattr(candidates[0].content, "parts", [])
                    if parts:
                        return parts[0].text
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
                raise  # caller decides whether to try next model

    raise RuntimeError(f"{model}: falhou apos {len(_BACKOFF)+1} tentativas.")


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

    # Text macros in geometry layer → likely causes compile errors
    if re.search(r"\\Book\w+", block):
        warnings.append(
            "AVISO: macros \\Book* detectadas — modelo incluiu texto na camada "
            "geometrica. Pode causar erro de compilacao."
        )

    # Pixel-range numbers (anything over 150 is suspicious for an A4 cover in cm)
    # Exclude: hex color codes in \definecolor, arc degree angles (multiples of 90)
    _clean = re.sub(r"\\definecolor\{[^}]+\}\{HTML\}\{[0-9A-Fa-f]+\}", "", block)
    _clean = re.sub(r"arc\s*\([^)]*\)", "", _clean)   # strip arc() angle args
    numbers = re.findall(r"(?<![a-zA-Z{])(\d{3,}\.?\d*)", _clean)
    suspect = [n for n in numbers if float(n) > 150]
    if suspect:
        warnings.append(
            f"AVISO: valores numericos suspeitos (possivelmente pixels): "
            f"{suspect[:5]} — esperado range 0–30 cm."
        )

    return warnings


# ─── Cover layout extraction ─────────────────────────────────────────────────
#
# The Vision prompt asks the VLM to emit a COVER_LAYOUT block after the TikZ
# geometry. We extract it here, validate each \renewcommand line against a
# strict allowlist, and pass it through to versatus-dynamic-cover.tex where it
# overrides the \providecommand defaults in versatus-covers.sty.

_LAYOUT_START = "% === COVER_LAYOUT ==="
_LAYOUT_END   = "% === END_COVER_LAYOUT ==="

# Strict allowlist: (matched_command_name, arg_value_regex)
# Keys are the ACTUAL LaTeX command strings (single backslash), matching what
# re.group(1) will capture. re.escape() is used when building the line regex.
_LAYOUT_ALLOWLIST: "list[tuple[str, str]]" = [
    (r"\VSCoverTopMargin",       r"[0-9]+\.?[0-9]*cm"),
    (r"\VSCoverLeftIndent",      r"[0-9]+\.?[0-9]*cm"),
    (r"\VSCoverTextWidth",       r"0?\.[0-9]+"),
    (r"\VSCoverTitlePt",         r"[0-9]+\.?[0-9]*"),
    (r"\VSCoverTitleLeadPt",     r"[0-9]+\.?[0-9]*"),
    (r"\VSCoverSubtitlePt",      r"[0-9]+\.?[0-9]*"),
    (r"\VSCoverSubtitleLeadPt",  r"[0-9]+\.?[0-9]*"),
    (r"\VSCoverTitleAlign",      r"\\(?:raggedright|centering|raggedleft)"),
]
_LAYOUT_LINE_RE = re.compile(
    r"^\\renewcommand\{(" + "|".join(re.escape(n) for n, _ in _LAYOUT_ALLOWLIST) + r")\}"
    r"\{([^}]+)\}$"
)
_LAYOUT_ARG_RE  = {name: re.compile(r"^" + pat + r"$")
                   for name, pat in _LAYOUT_ALLOWLIST}


def _extract_layout_block(text: str) -> "tuple[str, bool]":
    """
    Extract and validate the COVER_LAYOUT block from the VLM response.

    Returns (validated_latex_snippet, found) where:
    - validated_latex_snippet is a string of safe \\renewcommand lines (may be
      shorter than what the VLM emitted if some lines failed validation)
    - found is True iff the delimiters were present in text
    """
    start = text.find(_LAYOUT_START)
    end   = text.find(_LAYOUT_END)
    if start == -1 or end == -1 or end <= start:
        return "", False

    raw_lines = text[start + len(_LAYOUT_START): end].splitlines()
    safe_lines: "list[str]" = []

    for raw in raw_lines:
        line = raw.strip()
        if not line or line.startswith("%"):
            continue
        m = _LAYOUT_LINE_RE.match(line)
        if not m:
            continue  # unknown command or format — skip silently
        cmd_name = m.group(1)
        arg_val  = m.group(2)
        pat      = _LAYOUT_ARG_RE.get(cmd_name)
        if pat and pat.match(arg_val):
            safe_lines.append(line)

    if not safe_lines:
        return "", True  # found delimiters but nothing valid

    block = (
        "% === Cover layout extracted from reference image ===\n"
        + "\n".join(safe_lines)
        + "\n% === end cover layout ===\n"
    )
    return block, True


# ─── Public API ───────────────────────────────────────────────────────────────

def extract_tikz(
    image_path: "str | Path",
    output_tex: "str | Path | None" = None,
    brand: "str | None" = None,
) -> Path:
    """
    Run the full pipeline: image → Gemini Vision → TikZ macro written to disk.

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

    # ── 1. Prompt ─────────────────────────────────────────────────────────────
    print("[1/3] Carregando prompt de visao…")
    system_prompt = _load_prompt()

    brand_colors: "dict[str, str] | None" = None
    brand_data:   dict                   = {}
    if brand:
        brand_data   = _load_brand(brand)
        brand_colors = brand_data.get("colors", {})
        print(f"    Brand  : {brand_data.get('company', brand)} ({len(brand_colors)} cores)")

    color_block   = _build_color_instructions(brand_colors)
    system_prompt = system_prompt.replace("{{COLOR_INSTRUCTIONS}}", color_block)
    print(f"    Prompt : {_PROMPT_PATH.name} ({len(system_prompt)} chars)")

    # ── 2. Vision API — itera modelos ate obter bloco TikZ completo ───────────
    print("[2/3] Chamando Gemini Vision…")
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    _env_model = os.environ.get("GEMINI_MODEL", "").strip()
    if _env_model.startswith("models/"):
        _env_model = _env_model[len("models/"):]
    model_chain = [_env_model] if _env_model else _GEMINI_CHAIN

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
                image_path, system_prompt, _model, image_bytes, mime, client
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

    # ── 3. Cover layout extraction ────────────────────────────────────────────
    layout_block = ""
    layout_found, layout_valid = False, False
    if last_raw:
        layout_block, layout_found = _extract_layout_block(last_raw)
        layout_valid = bool(layout_block)
        if layout_found and layout_valid:
            n_cmds = layout_block.count("\\renewcommand")
            print(f"    [layout] {n_cmds} parâmetro(s) de layout extraídos da imagem.")
        elif layout_found:
            print("    [!] [layout] bloco COVER_LAYOUT presente mas sem linhas válidas — usando defaults.")
        else:
            print("    [!] [layout] bloco COVER_LAYOUT ausente na resposta — usando defaults do .sty.")

    # ── 4. Brand color enforcement (deterministic, no LLM involved) ──────────
    if brand_colors:
        block, off_palette = _enforce_brand_colors(block, brand_colors)
        if off_palette:
            print(
                f"    [!] Cores fora da paleta da marca (mantidas como geradas): "
                f"{sorted(set(off_palette))}"
            )
        else:
            print(f"    [OK] Todas as cores forcadas para a paleta de '{brand}'.")

    # ── 3b. Text panel — inject a solid (semi-transparent) rect before logo ─────
    # Drawn after the geometry and before the logo so it sits between them.
    # Activated only when brand.json defines a "text_panel" key.
    if brand and brand_data:
        tp = brand_data.get("text_panel")
        if tp:
            color   = tp.get("color", "bg_primary")
            opacity = tp.get("opacity", 1.0)
            x1, y1  = tp.get("x1", -1), tp.get("y1", 0)
            x2, y2  = tp.get("x2", 22), tp.get("y2", 20)
            op_str  = f", fill opacity={opacity}" if opacity < 1.0 else ""
            panel_line = f"  \\fill[{color}{op_str}] ({x1}, {y1}) rectangle ({x2}, {y2});"
            end_marker = "\\end{tikzpicture}%"
            if end_marker in block:
                block = block.replace(end_marker, panel_line + "\n" + end_marker, 1)
                print(
                    f"    [panel] painel de texto injetado: {color} "
                    f"[({x1},{y1})→({x2},{y2})], opacity={opacity}"
                )

    # ── 3c. Logo intelligence — pick variant by bg_primary luminance ──────────
    logo_inline     = ""
    logo_macro_name = ""
    if brand and brand_colors:
        bg_hex    = str(brand_colors.get("bg_primary", "#808080")).lstrip("#")
        lum       = _luminance(bg_hex)
        available = set(brand_data.get("logos", {}).keys())
        variant   = _choose_logo_variant(bg_hex, available)

        brand_dir_path          = _BRANDS_DIR / brand
        logo_inline, logo_macro_name = _inline_logo(
            brand_dir_path, brand_data, variant, brand
        )

        if logo_macro_name:
            # Position: read from brand.json["logo_position"] or use default top-left
            pos = brand_data.get("logo_position", [1.5, 26.5])
            logo_call  = f"  \\{logo_macro_name}{{({pos[0]}, {pos[1]})}}"
            end_marker = "\\end{tikzpicture}%"
            if end_marker in block:
                block = block.replace(end_marker, logo_call + "\n" + end_marker, 1)
                print(
                    f"    [logo] variante '{variant}' selecionada "
                    f"(luminancia bg_primary: {lum:.3f}) -> \\{logo_macro_name}"
                )
            else:
                print(f"    [!] [logo] \\end{{tikzpicture}}% nao encontrado no bloco.")
        else:
            print(f"    [!] [logo] {logo_inline.strip()}")

    # ── 3d. Brand preamble — font + VS color aliases ──────────────────────────
    brand_preamble = ""
    if brand and brand_colors:
        brand_preamble = _build_brand_preamble(brand, brand_data, brand_colors)
        print(
            f"    [font] {brand_data.get('font', 'N/A')} "
            f"(com fallback Noto Sans / Latin Modern Sans)"
        )

    # ── 4. Validate + write ───────────────────────────────────────────────────
    print("[3/3] Validando e escrevendo macro TikZ…")
    for warning in _validate_tikz(block):
        print(f"    {warning}")

    brand_note = f" (brand: {brand})" if brand else ""
    header     = f"% Auto-generated by vision_extractor.py{brand_note} - DO NOT EDIT MANUALLY\n"
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    tex_path.write_text(
        header + brand_preamble + layout_block + logo_inline + block + "\n",
        encoding="utf-8",
    )
    print(f"    Macro TikZ escrita → {tex_path}")

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
