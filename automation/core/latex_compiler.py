#!/usr/bin/env python3
"""
latex_compiler.py — Self-healing LuaLaTeX compiler with Gemini-powered repair loop.

Converts a Canvas AST JSON → TikZ macro, compiles with LuaLaTeX via latexmk,
and on failure: extracts the log error, asks Gemini to repair the JSON, and
retries — up to max_retries times.

Log/PDF paths are derived from the tex_file stem at runtime (from latexmkrc):
    Log : build/aux/<stem>.log
    PDF : build/pdf/<stem>.pdf

CLI usage:
    python latex_compiler.py <project_root> <canvas.json> [output.tex] [main-dynamic.tex]
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────

_HERE             = Path(__file__).resolve().parent          # automation/core/
_AUTOMATION       = _HERE.parent                             # automation/
_REPAIR_PROMPT    = _AUTOMATION / "prompt" / "repair_prompt.txt"

# Log and PDF paths are derived dynamically from the tex_file stem in
# compile_with_healing(), matching latexmkrc: $out_dir='build/pdf', $aux_dir='build/aux'

# ─── Custom exception ─────────────────────────────────────────────────────────

class CompilationError(RuntimeError):
    """Raised when LaTeX compilation fails after all self-healing attempts."""
    def __init__(
        self,
        message:  str,
        attempt:  int,
        errors:   list[str],
        log_path: "Path | None",
    ):
        super().__init__(message)
        self.attempt  = attempt
        self.errors   = errors
        self.log_path = log_path

# ─── Module loader (avoids sys.path pollution) ────────────────────────────────

def _load_module(name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(name, file_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# ─── LaTeX compilation ────────────────────────────────────────────────────────

def _run_latexmk(
    project_root: Path,
    tex_file:     str = "main.tex",
    timeout:      int = 180,
) -> tuple[int, "Path | None"]:
    """
    Run `latexmk -lualatex -f <tex_file>` from project_root.

    Returns
    -------
    (exit_code, log_path)
        log_path is None if the log file cannot be found after compilation.
    """
    result = subprocess.run(
        ["latexmk", "-lualatex", "-f", tex_file],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )

    # Resolve log path: latexmkrc sends aux files to build/aux/
    stem = Path(tex_file).stem
    candidates = [
        project_root / "build" / "aux" / f"{stem}.log",
        project_root / f"{stem}.log",          # fallback: no out_dir config
    ]
    log_path = next((p for p in candidates if p.exists()), None)

    return result.returncode, log_path

# ─── Log parsing ─────────────────────────────────────────────────────────────

# Lines that signal the start of a LaTeX error block
_ERROR_START_RE = re.compile(
    r"^("
    r"!"                          # generic TeX error
    r"|Package \w[\w@]* Error:"   # package-level errors (xcolor, pgf, tikz…)
    r"|LaTeX Error:"              # core LaTeX errors
    r"|Runaway argument\?"        # unclosed group
    r"|Emergency stop\."          # fatal abort
    r"|.*Fatal error.*"           # lualatex fatal messages
    r")",
    re.IGNORECASE,
)

# Lines with source file/line references (e.g. "l.42  \fill[...")
_LINE_REF_RE = re.compile(r"^l\.(\d+)\s")


def _extract_errors(log_path: "Path | None", context_lines: int = 10) -> list[str]:
    """
    Parse the LaTeX log file and return a list of error blocks.

    Each block contains the error-trigger line plus up to context_lines of
    following context (which often includes the offending TikZ command and
    the l.<n> source reference).
    """
    if not log_path or not log_path.exists():
        return [f"[log file not found: {log_path}]"]

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    blocks: list[str] = []
    seen: set[str] = set()   # deduplicate identical error messages
    i = 0

    while i < len(lines):
        if _ERROR_START_RE.match(lines[i]):
            block_lines = lines[i : i + context_lines]
            block = "\n".join(block_lines).strip()
            key   = lines[i].strip()           # first line as dedup key
            if key not in seen:
                seen.add(key)
                blocks.append(block)
            i += context_lines
        else:
            i += 1

    return blocks or ["[no structured error pattern found in log — see full log]"]

# ─── Gemini repair call ───────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?\s*```$", re.DOTALL)


def _clean_json(text: str) -> str:
    text = text.strip()
    m = _FENCE_RE.match(text)
    return m.group(1).strip() if m else text


def _call_gemini_repair(
    canvas_data:  dict,
    tikz_code:    str,
    error_blocks: list[str],
    attempt:      int,
) -> dict:
    """
    Send the broken JSON + TikZ code + log errors to Gemini and return the
    corrected Canvas AST JSON as a Python dict.

    Raises
    ------
    json.JSONDecodeError  If the model returns malformed JSON.
    EnvironmentError      If GEMINI_API_KEY is not set.
    ImportError           If google-genai is not installed.
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise ImportError("pip install google-genai") from exc

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set.")

    _env_model = os.environ.get("GEMINI_MODEL", "").strip()
    _CHAIN     = [_env_model] if _env_model else [
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash-8b",
        "gemini-2.5-flash",
    ]
    system_prompt  = _REPAIR_PROMPT.read_text(encoding="utf-8")
    error_summary  = "\n\n".join(
        f"--- Error block {i + 1} ---\n{b}"
        for i, b in enumerate(error_blocks)
    )
    canvas_str = json.dumps(canvas_data, ensure_ascii=False, indent=2)

    user_message = (
        f"=== REPAIR REQUEST (attempt {attempt}) ===\n\n"
        f"=== CANVAS AST JSON (caused the error below) ===\n"
        f"{canvas_str}\n\n"
        f"=== GENERATED TikZ CODE ===\n"
        f"{tikz_code}\n\n"
        f"=== LaTeX ERROR LOG EXCERPT ===\n"
        f"{error_summary}\n\n"
        "Return the corrected Canvas AST JSON."
    )

    client   = genai.Client(http_options={"api_version": "v1beta"})
    _BACKOFF = [10, 20]   # segundos entre tentativas no caso de 503
    response = None

    for _midx, _model in enumerate(_CHAIN):
        print(f"  [repair] Model: {_model}")
        _need_switch = False
        for _try in range(len(_BACKOFF) + 1):
            try:
                response = client.models.generate_content(
                    model=_model,
                    contents=[
                        types.Content(
                            role="user",
                            parts=[types.Part(text=user_message)],
                        )
                    ],
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.1,
                        max_output_tokens=8192,
                    ),
                )
                break  # sucesso
            except Exception as _exc:
                _s        = str(_exc)
                _is_busy  = "503" in _s or "UNAVAILABLE" in _s
                _is_rate  = "429" in _s or "RESOURCE_EXHAUSTED" in _s
                _has_next = _midx < len(_CHAIN) - 1
                if _is_busy and _try < len(_BACKOFF):
                    _w = _BACKOFF[_try]
                    print(f"  [!] {_model}: sobrecarregado — tentando novamente em {_w}s…")
                    time.sleep(_w)
                elif (_is_rate or _is_busy) and _has_next:
                    print(f"  [!] {_model}: indisponível — alternando para {_CHAIN[_midx + 1]}…")
                    _need_switch = True
                    break
                else:
                    raise
        if _need_switch:
            continue
        break  # sucesso ou exceção lançada acima

    try:
        raw_text = response.text
    except (AttributeError, ValueError) as exc:
        candidates = getattr(response, "candidates", [])
        if candidates:
            parts = getattr(candidates[0].content, "parts", [])
            if parts:
                raw_text = parts[0].text
            else:
                finish = getattr(candidates[0], "finish_reason", "UNKNOWN")
                raise RuntimeError(f"Model returned no text (finish_reason={finish}).") from exc
        else:
            raise RuntimeError("Model returned no candidates.") from exc

    return json.loads(_clean_json(raw_text))

# ─── Public API ───────────────────────────────────────────────────────────────

def compile_with_healing(
    project_root:     "str | Path",
    canvas_json_path: "str | Path | None" = None,
    output_tex_path:  "str | Path | None" = None,
    tex_file:         str = "main-dynamic.tex",
    max_retries:      int = 3,
    tikz_ready:       bool = False,
) -> Path:
    """
    Compile the dynamic cover with LuaLaTeX.

    When tikz_ready=False (legacy mode): converts canvas_json_path → TikZ first,
    then compiles, with Gemini-powered JSON repair on failure.

    When tikz_ready=True (direct TikZ mode): the .tex macro is already written
    by vision_extractor.extract_tikz(); just compile with LuaLaTeX directly.

    Parameters
    ----------
    project_root : Path
        Root directory of the LaTeX project.
    canvas_json_path : Path or None
        Canvas AST JSON. Required when tikz_ready=False; ignored when True.
    output_tex_path : Path or None
        The generated .tex macro file.
        Default: <project_root>/styles/versatus-dynamic-cover.tex
    tex_file : str
        LaTeX entry-point filename (default: "main-dynamic.tex").
    max_retries : int
        Maximum compile attempts (default: 3).
    tikz_ready : bool
        When True, skip JSON→TikZ conversion and compile directly.

    Returns
    -------
    Path
        Path to the successfully compiled PDF.

    Raises
    ------
    CompilationError
        If compilation fails after all retries are exhausted.
    """
    project_root    = Path(project_root).resolve()
    _canonical_tex  = project_root / "styles" / "versatus-dynamic-cover.tex"

    if output_tex_path is None:
        output_tex_path = _canonical_tex
    else:
        output_tex_path = Path(output_tex_path).resolve()

    _stem    = Path(tex_file).stem
    pdf_path = project_root / "build" / "pdf" / f"{_stem}.pdf"

    last_errors: list[str]    = []
    log_path:    "Path | None" = None

    # ── Direct TikZ mode — single compile, no JSON repair ────────────────────
    if tikz_ready:
        _banner(1, 1)
        print(f"  [1/2] Macro TikZ: {output_tex_path.relative_to(project_root)}")
        # main-dynamic.tex hardcodes \input{styles/versatus-dynamic-cover}, so
        # whatever was actually written to output_tex_path must land there too
        # before latexmk runs — otherwise a custom --tex path is silently
        # ignored and a stale cover gets compiled instead.
        if output_tex_path.resolve() != _canonical_tex.resolve():
            _canonical_tex.parent.mkdir(parents=True, exist_ok=True)
            _canonical_tex.write_text(
                output_tex_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
            print(f"        -> copiado para {_canonical_tex.relative_to(project_root)} (caminho compilado de fato)")
        print(f"  [2/2] Rodando latexmk -lualatex -f {tex_file}…")
        try:
            exit_code, log_path = _run_latexmk(project_root, tex_file)
        except subprocess.TimeoutExpired:
            raise CompilationError(
                "latexmk excedeu o tempo limite.",
                attempt=1, errors=["timeout"], log_path=None,
            )
        if exit_code == 0:
            print(f"  [OK] Compilacao concluida → {pdf_path.relative_to(project_root)}")
            return pdf_path

        last_errors = _extract_errors(log_path)
        _print_error_summary(last_errors)
        raise CompilationError(
            f"Compilacao LaTeX falhou.\nLog: {log_path}\n\n"
            + "\n\n".join(last_errors),
            attempt=1, errors=last_errors, log_path=log_path,
        )

    # ── Legacy JSON→TikZ mode ────────────────────────────────────────────────
    if canvas_json_path is None:
        raise ValueError(
            "canvas_json_path e obrigatorio quando tikz_ready=False."
        )
    canvas_json_path = Path(canvas_json_path).resolve()

    tikz_mod     = _load_module("json_to_tikz", _HERE / "json_to_tikz.py")
    tikz_convert = tikz_mod.convert
    canvas_data  = json.loads(canvas_json_path.read_text(encoding="utf-8"))

    for attempt in range(1, max_retries + 1):
        _banner(attempt, max_retries)

        # Step 1: JSON → TikZ
        print("  [1/3] Generating TikZ macro from Canvas AST…")
        try:
            tikz_convert(canvas_json_path, output_path=output_tex_path)
            tikz_code = output_tex_path.read_text(encoding="utf-8")
        except Exception as exc:
            last_errors = [f"JSON->TikZ conversion failed: {exc}"]
            tikz_code   = ""
            print(f"       [!] Conversion error: {exc}")
            _maybe_repair(
                attempt, max_retries, canvas_data, tikz_code,
                last_errors, canvas_json_path,
            )
            if attempt < max_retries:
                canvas_data = json.loads(canvas_json_path.read_text(encoding="utf-8"))
            continue

        # Step 2: Compile
        print(f"  [2/3] Running latexmk -lualatex -f {tex_file}…")
        try:
            exit_code, log_path = _run_latexmk(project_root, tex_file)
        except subprocess.TimeoutExpired:
            last_errors = ["[latexmk timed out]"]
            exit_code   = -1

        if exit_code == 0:
            print(f"  [OK] Compilation succeeded → {pdf_path.relative_to(project_root)}")
            return pdf_path

        # Step 3: Parse log & repair
        print(f"  [X] Compilation failed (exit {exit_code}). Parsing log…")
        last_errors = _extract_errors(log_path)
        _print_error_summary(last_errors)
        _maybe_repair(
            attempt, max_retries, canvas_data, tikz_code,
            last_errors, canvas_json_path,
        )
        if attempt < max_retries:
            canvas_data = json.loads(canvas_json_path.read_text(encoding="utf-8"))

    error_summary = "\n\n".join(last_errors)
    raise CompilationError(
        f"LaTeX compilation failed after {max_retries} attempt(s).\n"
        f"Log: {log_path}\n\n{error_summary}",
        attempt=max_retries, errors=last_errors, log_path=log_path,
    )


def _maybe_repair(
    attempt:          int,
    max_retries:      int,
    canvas_data:      dict,
    tikz_code:        str,
    errors:           list[str],
    canvas_json_path: Path,
) -> None:
    """Call Gemini repair and overwrite canvas_json_path if not on final attempt."""
    if attempt >= max_retries:
        print(f"  [!] Retry limit ({max_retries}) reached — aborting.")
        return

    print(f"  [3/3] Requesting repair from LLM (attempt {attempt}/{max_retries - 1})…")
    try:
        repaired    = _call_gemini_repair(canvas_data, tikz_code, errors, attempt)
        canvas_json_path.write_text(
            json.dumps(repaired, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"       Repaired JSON saved → {canvas_json_path.name}")
    except json.JSONDecodeError as exc:
        print(f"       [!] LLM returned invalid JSON during repair (will retry same): {exc}")
    except Exception as exc:
        print(f"       [!] Repair call failed: {type(exc).__name__}: {exc}")


def _banner(attempt: int, total: int) -> None:
    width = 60
    label = f"  Attempt {attempt} / {total}  "
    pad   = (width - len(label)) // 2
    print(f"\n{'-' * pad}{label}{'-' * pad}")


def _print_error_summary(errors: list[str]) -> None:
    for i, block in enumerate(errors, 1):
        first_line = block.splitlines()[0][:110]
        print(f"       Error {i}: {first_line}")

# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    usage = (
        f"Usage: python {Path(__file__).name} "
        "<project_root> <canvas.json> [output.tex] [main.tex]\n\n"
        "Required env var:  GEMINI_API_KEY\n"
        "Optional env var:  GEMINI_MODEL  (default: gemini-2.0-flash-lite)"
    )
    if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):
        print(usage)
        sys.exit(0)

    root    = sys.argv[1]
    canvas  = sys.argv[2]
    tex_out = sys.argv[3] if len(sys.argv) > 3 else None
    main    = sys.argv[4] if len(sys.argv) > 4 else "main-dynamic.tex"

    try:
        pdf = compile_with_healing(root, canvas, tex_out, main)
        print(f"\n[DONE] PDF ready: {pdf}")
    except CompilationError as exc:
        print(f"\n[FAILED] {exc}", file=sys.stderr)
        sys.exit(5)
    except Exception as exc:
        import traceback
        print(f"\n[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(6)
