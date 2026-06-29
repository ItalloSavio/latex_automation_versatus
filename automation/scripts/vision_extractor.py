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

import os
import re
import sys
import time
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────

_HERE        = Path(__file__).resolve().parent   # automation/scripts/
_AUTOMATION  = _HERE.parent                       # automation/
_PROMPT_PATH = _AUTOMATION / "prompt" / "vision_prompt.txt"
_OUTPUT_DIR  = _AUTOMATION / "output"
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


# ─── Public API ───────────────────────────────────────────────────────────────

def extract_tikz(
    image_path: "str | Path",
    output_tex: "str | Path | None" = None,
) -> Path:
    """
    Run the full pipeline: image → Gemini Vision → TikZ macro written to disk.

    Parameters
    ----------
    image_path : str or Path
        Path to the cover image (PNG / JPEG / WEBP).
    output_tex : str, Path, or None
        Destination .tex file. Default: styles/versatus-dynamic-cover.tex

    Returns
    -------
    Path
        Path of the written .tex file.

    Raises
    ------
    FileNotFoundError       Image or prompt not found.
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

    # ── 3. Validate + write ───────────────────────────────────────────────────
    print("[3/3] Validando e escrevendo macro TikZ…")
    for warning in _validate_tikz(block):
        print(f"    {warning}")

    header = "% Auto-generated by vision_extractor.py — DO NOT EDIT MANUALLY\n"
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    tex_path.write_text(header + block + "\n", encoding="utf-8")
    print(f"    Macro TikZ escrita → {tex_path}")

    return tex_path


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    usage = (
        f"Usage: python {Path(__file__).name} "
        "<imagem.(png|jpg|jpeg|webp)> [output.tex]\n\n"
        "Env var obrigatoria:\n"
        "  GEMINI_API_KEY  Chave do Google AI Studio\n\n"
        "Env var opcional:\n"
        "  GEMINI_MODEL    Modelo a usar (default: gemini-3-flash-preview)"
    )

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(usage)
        sys.exit(0)

    try:
        t = extract_tikz(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
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
