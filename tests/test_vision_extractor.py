"""
Unit tests for pure-Python functions in vision_extractor.py.
No API key, no network, no LaTeX required — runs fully offline.

Run:
    pip install pytest
    pytest tests/ -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "automation" / "scripts"))

import vision_extractor as ve


# ─── Shared test fixtures ─────────────────────────────────────────────────────

# Minimal block — used for structural / parsing tests (no LOGO_PLACEMENT, no macros)
_SIMPLE_BLOCK = (
    r"\newcommand{\RenderDynamicCover}{"
    r"\begin{tikzpicture}"
    r"\fill[bg_primary](0,0) rectangle (21,29.7);"
    r"\end{tikzpicture}%"
    r"}"
)

# Complete valid block — passes ALL _validate_tikz checks
_VALID_BLOCK = (
    "\\newcommand{\\RenderDynamicCover}{%\n"
    "% LOGO_PLACEMENT x=1.5 y=26.5 height=2.0 bg=bg_primary\n"
    "\\definecolor{bg_primary}{HTML}{201F1E}\n"
    "\\begin{tikzpicture}\n"
    "\\fill[bg_primary](-1,-1) rectangle (22,30.7);\n"
    "\\node at (1.5,24) {\\BookTitle};\n"
    "\\node at (1.5,20) {\\BookSubtitle};\n"
    "\\node at (1.5,17) {\\BookDescription};\n"
    "\\node at (1.5,5)  {\\BookAuthor};\n"
    "\\node at (1.5,3)  {\\BookDate};\n"
    "\\node at (1.5,2)  {\\BookVersion};\n"
    "\\end{tikzpicture}%\n"
    "}"
)


# ─── Color math ───────────────────────────────────────────────────────────────

class TestSrgbLinearize:
    def test_zero(self):
        assert ve._srgb_linearize(0.0) == pytest.approx(0.0)

    def test_one(self):
        assert ve._srgb_linearize(1.0) == pytest.approx(1.0)

    def test_below_threshold(self):
        # c <= 0.04045 → c / 12.92
        assert ve._srgb_linearize(0.04045) == pytest.approx(0.04045 / 12.92, rel=1e-6)

    def test_above_threshold(self):
        # c > 0.04045 → ((c + 0.055) / 1.055) ** 2.4
        c = 0.5
        expected = ((c + 0.055) / 1.055) ** 2.4
        assert ve._srgb_linearize(c) == pytest.approx(expected, rel=1e-6)


class TestLuminance:
    def test_black(self):
        assert ve._luminance("000000") == pytest.approx(0.0)

    def test_white(self):
        assert ve._luminance("FFFFFF") == pytest.approx(1.0)

    def test_pure_red(self):
        # Only R channel active: 0.2126 * linearize(1.0) = 0.2126
        assert ve._luminance("FF0000") == pytest.approx(0.2126, rel=1e-4)

    def test_pure_green(self):
        assert ve._luminance("00FF00") == pytest.approx(0.7152, rel=1e-4)

    def test_pure_blue(self):
        assert ve._luminance("0000FF") == pytest.approx(0.0722, rel=1e-4)

    def test_with_hash_prefix(self):
        assert ve._luminance("#FFFFFF") == pytest.approx(1.0)

    def test_lowercase_hex(self):
        assert ve._luminance("ffffff") == pytest.approx(1.0)

    def test_dark_background(self):
        # VSBlack #201F1E — luminance should be < 0.02 (very dark)
        lum = ve._luminance("201F1E")
        assert lum < 0.02

    def test_vs_red(self):
        # VSRed #DD4F51 — dark enough that it's < 0.35 (dark bg territory)
        lum = ve._luminance("DD4F51")
        assert 0.15 < lum < 0.30


class TestContrastRatio:
    def test_white_vs_black(self):
        ratio = ve._contrast_ratio("FFFFFF", "000000")
        assert ratio == pytest.approx(21.0, rel=1e-3)

    def test_same_color_white(self):
        assert ve._contrast_ratio("FFFFFF", "FFFFFF") == pytest.approx(1.0)

    def test_same_color_black(self):
        assert ve._contrast_ratio("000000", "000000") == pytest.approx(1.0)

    def test_symmetry(self):
        a, b = "DD4F51", "FFFFFF"
        assert ve._contrast_ratio(a, b) == pytest.approx(ve._contrast_ratio(b, a))

    def test_always_at_least_one(self):
        for hex_pair in [("000000", "FFFFFF"), ("201F1E", "DD4F51"), ("4CB6B4", "FFFFFF")]:
            assert ve._contrast_ratio(*hex_pair) >= 1.0

    def test_muted_vs_white_has_reasonable_contrast(self):
        # VSMutedText #5D5956 on white paper should be > 4.5:1 (WCAG AA)
        ratio = ve._contrast_ratio("5D5956", "FFFFFF")
        assert ratio > 4.5


class TestBlendHex:
    def test_factor_zero_returns_base(self):
        assert ve._blend_hex("FF0000", "0000FF", 0.0) == "FF0000"

    def test_factor_one_returns_toward(self):
        assert ve._blend_hex("FF0000", "0000FF", 1.0) == "0000FF"

    def test_midpoint(self):
        # R: round(255*0.5 + 0*0.5) = 128 = 0x80
        # G: 0
        # B: round(0*0.5 + 255*0.5) = 128 = 0x80
        result = ve._blend_hex("FF0000", "0000FF", 0.5)
        assert result == "800080"

    def test_white_toward_black(self):
        # 14% toward black: 255 * 0.86 = 219.3 → 219 = 0xDB
        result = ve._blend_hex("FFFFFF", "000000", 0.14)
        r = int(result[0:2], 16)
        assert 215 <= r <= 221  # approx 0xDB

    def test_output_is_uppercase_hex(self):
        result = ve._blend_hex("aabbcc", "112233", 0.5)
        assert result == result.upper()
        assert len(result) == 6


# ─── String utilities ─────────────────────────────────────────────────────────

class TestPascal:
    def test_single_word(self):
        assert ve._pascal("versatus") == "Versatus"

    def test_hyphen_separated(self):
        assert ve._pascal("my-brand") == "MyBrand"

    def test_underscore_separated(self):
        assert ve._pascal("my_brand") == "MyBrand"

    def test_mixed_separators(self):
        assert ve._pascal("long-brand_name") == "LongBrandName"

    def test_already_pascal(self):
        assert ve._pascal("Versatus") == "Versatus"

    def test_empty(self):
        assert ve._pascal("") == ""


# ─── Logo variant selection ───────────────────────────────────────────────────

class TestChooseLogoVariant:
    _ALL = {"dark", "light", "alt"}

    def test_dark_bg_prefers_dark(self):
        # #000000 → lum=0 → dark background → prefer "dark"
        assert ve._choose_logo_variant("000000", self._ALL) == "dark"

    def test_light_bg_prefers_light(self):
        # #FFFFFF → lum=1 → light background → prefer "light"
        assert ve._choose_logo_variant("FFFFFF", self._ALL) == "light"

    def test_mid_bg_prefers_alt(self):
        # #B0B0B0 → lum ≈ 0.46 (between 0.35 and 0.60) → prefer "alt"
        assert ve._choose_logo_variant("B0B0B0", self._ALL) == "alt"

    def test_fallback_when_preferred_missing(self):
        # Dark bg but only "light" available → falls back to "light"
        result = ve._choose_logo_variant("000000", {"light"})
        assert result == "light"

    def test_alt_fallback_for_dark_bg(self):
        # Dark bg, "dark" missing → try "alt"
        result = ve._choose_logo_variant("000000", {"alt", "light"})
        assert result == "alt"

    def test_empty_set_returns_dark(self):
        # next(iter(set())) on empty set would error — but the function returns "dark"
        result = ve._choose_logo_variant("000000", set())
        assert result == "dark"


# ─── TikZ block extraction ────────────────────────────────────────────────────

class TestExtractTikzBlock:
    def test_complete_block_returns_ok(self):
        block, status = ve._extract_tikz_block(_SIMPLE_BLOCK)
        assert status == "ok"
        assert block is not None
        assert block.startswith(r"\newcommand{\RenderDynamicCover}")

    def test_strips_markdown_fences(self):
        fenced = "```latex\n" + _SIMPLE_BLOCK + "\n```"
        block, status = ve._extract_tikz_block(fenced)
        assert status == "ok"
        assert "```" not in block

    def test_strips_tex_fences(self):
        fenced = "```tex\n" + _SIMPLE_BLOCK + "\n```"
        block, status = ve._extract_tikz_block(fenced)
        assert status == "ok"

    def test_not_found(self):
        block, status = ve._extract_tikz_block("This is just some text with no TikZ.")
        assert status == "not_found"
        assert block is None

    def test_truncated(self):
        # Missing closing brace
        truncated = r"\newcommand{\RenderDynamicCover}{\begin{tikzpicture}\fill"
        block, status = ve._extract_tikz_block(truncated)
        assert status == "truncated"
        assert block is None

    def test_nested_braces_balanced(self):
        nested = (
            r"\newcommand{\RenderDynamicCover}{"
            r"\begin{tikzpicture}"
            r"\node{\textbf{Hello}};"
            r"\end{tikzpicture}%"
            r"}"
        )
        block, status = ve._extract_tikz_block(nested)
        assert status == "ok"
        assert r"\textbf{Hello}" in block

    def test_block_content_is_exact_match(self):
        block, _ = ve._extract_tikz_block(_SIMPLE_BLOCK)
        assert block == _SIMPLE_BLOCK


# ─── TikZ validation ──────────────────────────────────────────────────────────

class TestValidateTikz:
    def test_valid_block_no_warnings(self):
        # _VALID_BLOCK has LOGO_PLACEMENT, bg= matching a declared color, and all 6 macros
        warnings = ve._validate_tikz(_VALID_BLOCK)
        assert warnings == []

    def test_missing_begin(self):
        bad = r"\newcommand{\RenderDynamicCover}{\end{tikzpicture}}"
        warnings = ve._validate_tikz(bad)
        assert any("begin" in w.lower() for w in warnings)

    def test_missing_end(self):
        bad = r"\newcommand{\RenderDynamicCover}{\begin{tikzpicture}}"
        warnings = ve._validate_tikz(bad)
        assert any("end" in w.lower() for w in warnings)

    def test_suspicious_large_numbers(self):
        bad = _SIMPLE_BLOCK.replace("(21,29.7)", "(1920,1080)")
        warnings = ve._validate_tikz(bad)
        assert any("suspeito" in w.lower() or "pixels" in w.lower() for w in warnings)

    def test_hex_codes_not_flagged(self):
        block_with_color = (
            r"\newcommand{\RenderDynamicCover}{"
            r"\definecolor{bg_primary}{HTML}{4CB6B4}"
            r"\begin{tikzpicture}\end{tikzpicture}%"
            r"}"
        )
        warnings = ve._validate_tikz(block_with_color)
        assert not any("suspeito" in w.lower() for w in warnings)


class TestValidateTikzLogoPlacement:
    def test_missing_logo_placement_warns(self):
        block = _VALID_BLOCK.replace("% LOGO_PLACEMENT x=1.5 y=26.5 height=2.0 bg=bg_primary\n", "")
        warnings = ve._validate_tikz(block)
        assert any("LOGO_PLACEMENT" in w for w in warnings)

    def test_logo_placement_present_no_warning(self):
        warnings = ve._validate_tikz(_VALID_BLOCK)
        assert not any("LOGO_PLACEMENT ausente" in w for w in warnings)

    def test_wrong_bg_role_warns(self):
        # "dark" is not a declared \definecolor role name
        block = _VALID_BLOCK.replace("bg=bg_primary", "bg=dark")
        warnings = ve._validate_tikz(block)
        assert any("dark" in w or "bg=" in w for w in warnings)

    def test_correct_bg_role_no_warning(self):
        # bg=bg_primary matches \definecolor{bg_primary}{HTML}{201F1E}
        warnings = ve._validate_tikz(_VALID_BLOCK)
        assert not any("nao corresponde" in w for w in warnings)

    def test_bg_role_case_sensitive(self):
        # "Bg_Primary" is not the same as "bg_primary"
        block = _VALID_BLOCK.replace("bg=bg_primary", "bg=Bg_Primary")
        warnings = ve._validate_tikz(block)
        assert any("Bg_Primary" in w or "nao corresponde" in w for w in warnings)


class TestValidateTikzRequiredMacros:
    def test_all_macros_present_no_warning(self):
        warnings = ve._validate_tikz(_VALID_BLOCK)
        assert not any("macros" in w.lower() for w in warnings)

    def test_missing_title_warns(self):
        block = _VALID_BLOCK.replace(r"\BookTitle", r"\Removed")
        warnings = ve._validate_tikz(block)
        assert any("BookTitle" in w for w in warnings)

    def test_missing_subtitle_warns(self):
        block = _VALID_BLOCK.replace(r"\BookSubtitle", "")
        warnings = ve._validate_tikz(block)
        assert any("BookSubtitle" in w for w in warnings)

    def test_missing_multiple_macros_reported_together(self):
        block = _VALID_BLOCK.replace(r"\BookDescription", "").replace(r"\BookAuthor", "")
        warnings = ve._validate_tikz(block)
        macro_warnings = [w for w in warnings if "macros" in w.lower()]
        assert len(macro_warnings) == 1  # single combined warning
        assert "BookDescription" in macro_warnings[0]
        assert "BookAuthor" in macro_warnings[0]

    def test_required_macros_constant_has_six_entries(self):
        assert len(ve._REQUIRED_MACROS) == 6


# ─── Brand color enforcement ──────────────────────────────────────────────────

class TestEnforceBrandColors:
    _COLORS = {
        "bg_primary": "#201F1E",
        "accent_1":   "#4CB6B4",
        "accent_2":   "#DD4F51",
    }

    def test_corrects_wrong_hex(self):
        block = r"\definecolor{bg_primary}{HTML}{AABBCC}"
        result, off = ve._enforce_brand_colors(block, self._COLORS)
        assert "201F1E" in result
        assert "AABBCC" not in result
        assert off == []

    def test_unknown_role_kept_as_is(self):
        block = r"\definecolor{custom_role}{HTML}{112233}"
        result, off = ve._enforce_brand_colors(block, self._COLORS)
        assert "112233" in result
        assert "custom_role" in off

    def test_all_roles_replaced(self):
        block = (
            r"\definecolor{bg_primary}{HTML}{000000}"
            r"\definecolor{accent_1}{HTML}{000000}"
            r"\definecolor{accent_2}{HTML}{000000}"
        )
        result, off = ve._enforce_brand_colors(block, self._COLORS)
        assert "201F1E" in result
        assert "4CB6B4" in result
        assert "DD4F51" in result
        assert off == []

    def test_empty_block(self):
        result, off = ve._enforce_brand_colors("", self._COLORS)
        assert result == ""
        assert off == []


# ─── Background detection from TikZ ──────────────────────────────────────────

class TestDetectBgFromTikz:
    _COLORS = {"bg_primary": "#201F1E", "accent_1": "#4CB6B4"}

    def test_finds_first_fill_role(self):
        block = r"\fill[bg_primary](0,0) rectangle (21,29.7);"
        result = ve._detect_bg_from_tikz(block, self._COLORS)
        assert result == "201F1E"

    def test_unknown_role_returns_empty(self):
        block = r"\fill[unknown_role](0,0) rectangle (21,29.7);"
        result = ve._detect_bg_from_tikz(block, self._COLORS)
        assert result == ""

    def test_no_fill_returns_empty(self):
        block = r"\draw[accent_1](0,0) -- (21,29.7);"
        result = ve._detect_bg_from_tikz(block, self._COLORS)
        assert result == ""

    def test_strips_hash_from_result(self):
        block = r"\fill[bg_primary](0,0) rectangle (21,29.7);"
        result = ve._detect_bg_from_tikz(block, self._COLORS)
        assert not result.startswith("#")


# ─── Logo placement parsing ───────────────────────────────────────────────────

class TestParseLogoPlacement:
    def test_valid_comment(self):
        block = "% LOGO_PLACEMENT x=1.5 y=26.5 height=2.0 bg=bg_primary\n\\fill..."
        result = ve._parse_logo_placement(block)
        assert result is not None
        assert result["x"] == 1.5
        assert result["y"] == 26.5
        assert result["height"] == 2.0
        assert result["bg"] == "bg_primary"

    def test_missing_returns_none(self):
        block = "\\fill[bg_primary](0,0) rectangle (21,29.7);"
        assert ve._parse_logo_placement(block) is None

    def test_integer_coordinates(self):
        block = "% LOGO_PLACEMENT x=1 y=26 height=3 bg=accent_1"
        result = ve._parse_logo_placement(block)
        assert result is not None
        assert result["x"] == 1.0
        assert result["y"] == 26.0


# ─── Color instructions builder ───────────────────────────────────────────────

class TestBuildColorInstructions:
    def test_none_returns_free_choice(self):
        result = ve._build_color_instructions(None)
        assert "Pick colors freely" in result

    def test_empty_dict_returns_free_choice(self):
        result = ve._build_color_instructions({})
        assert "Pick colors freely" in result

    def test_with_colors_contains_all_roles(self):
        colors = {"bg_primary": "#201F1E", "accent_1": "#4CB6B4"}
        result = ve._build_color_instructions(colors)
        assert "bg_primary" in result
        assert "accent_1" in result
        assert "201F1E" in result
        assert "4CB6B4" in result

    def test_strips_hash_from_hex(self):
        colors = {"bg_primary": "#AABBCC"}
        result = ve._build_color_instructions(colors)
        assert "AABBCC" in result
        assert "#AABBCC" not in result


# ─── MIME detection ───────────────────────────────────────────────────────────

class TestDetectMime:
    def test_png(self):
        assert ve._detect_mime(Path("cover.png")) == "image/png"

    def test_jpg(self):
        assert ve._detect_mime(Path("cover.jpg")) == "image/jpeg"

    def test_jpeg(self):
        assert ve._detect_mime(Path("cover.jpeg")) == "image/jpeg"

    def test_webp(self):
        assert ve._detect_mime(Path("cover.webp")) == "image/webp"

    def test_uppercase_extension(self):
        assert ve._detect_mime(Path("cover.PNG")) == "image/png"

    def test_unsupported_raises(self):
        with pytest.raises(ValueError, match="nao suportado"):
            ve._detect_mime(Path("cover.bmp"))


# ─── Model chain resolution ───────────────────────────────────────────────────

class TestResolveModelChain:
    def test_default_chain_when_no_env(self, monkeypatch):
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        chain = ve._resolve_model_chain()
        assert chain == ve._GEMINI_CHAIN
        assert len(chain) >= 2

    def test_env_overrides_chain(self, monkeypatch):
        monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
        chain = ve._resolve_model_chain()
        assert chain == ["gemini-test-model"]

    def test_strips_models_prefix(self, monkeypatch):
        monkeypatch.setenv("GEMINI_MODEL", "models/gemini-test-model")
        chain = ve._resolve_model_chain()
        assert chain == ["gemini-test-model"]


# ─── VSRed contrast fallback ─────────────────────────────────────────────────

class TestBuildBrandPreambleVSRedFallback:
    """Verify the VSRed → muted fallback when accent_2 ≈ bg_primary (Kosen case)."""

    def _make_preamble(self, bg: str, accent_2: str):
        brand_colors = {
            "bg_primary":  bg,
            "bg_secondary": "2B2928",
            "accent_1":    "4CB6B4",
            "accent_2":    accent_2,
            "light":       "FFFFFF",
            "muted":       "757576",
        }
        brand_data = {"company": "TestCo", "font": "Noto Sans", "colors": brand_colors}
        return ve._build_brand_preamble("testco", brand_data, brand_colors)

    def test_low_contrast_accent2_falls_back_to_muted(self):
        # Kosen: accent_2=#3B3CD0 vs bg_primary=#4038FF — very low contrast
        preamble = self._make_preamble("#4038FF", "#3B3CD0")
        # VSRed should NOT be 3B3CD0 (the original low-contrast accent_2)
        assert "3B3CD0" not in preamble or "VSRed" not in preamble.split("3B3CD0")[0]
        # VSRed should be muted (757576)
        assert "757576" in preamble

    def test_high_contrast_accent2_kept_as_is(self):
        # VSRed #DD4F51 vs bg_primary #201F1E — high contrast (bright on dark)
        preamble = self._make_preamble("#201F1E", "#DD4F51")
        assert "DD4F51" in preamble
