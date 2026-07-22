"""
Functional tests for the circle detector in image_analyzer.py.

Deterministic synthetic images (a drawn circle IS detectable) plus one test on
the real capa_teste1 concentric motif. No network, no LaTeX.

Run:
    pytest tests/test_circle_detector.py -v
"""

import sys
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "automation" / "scripts"))

import image_analyzer as ia  # noqa: E402

cv2 = pytest.importorskip("cv2")   # circle detection needs OpenCV

_BG   = [26, 26, 26]      # dark background (palette[0] by convention)
_RED  = [221, 79, 81]
_TEAL = [76, 181, 180]
_WHITE = [253, 254, 253]


def _palette(*rgbs):
    """Build a colors list like _extract_colors returns; first entry = background."""
    def _hex(c):
        return "#{:02X}{:02X}{:02X}".format(*c)
    return [{"hex": _hex(c), "rgb": list(c)} for c in ((_BG,) + rgbs)]


def _canvas(size=240):
    arr = np.empty((size, size, 3), np.uint8)
    arr[:] = _BG
    return arr


def _disk(arr, cx, cy, r, color):
    yy, xx = np.mgrid[0:arr.shape[0], 0:arr.shape[1]]
    arr[(xx - cx) ** 2 + (yy - cy) ** 2 <= r * r] = color


def _detect(arr, palette):
    h, w = arr.shape[:2]
    # cm scale is irrelevant to the geometry test; use pixel-equivalent cm
    return ia._detect_circles(arr, palette, w, h, float(w), float(h))


# ─── Deterministic synthetic tests ────────────────────────────────────────────

def test_detects_single_filled_circle():
    arr = _canvas()
    _disk(arr, 120, 120, 45, _RED)
    circles = _detect(arr, _palette(_RED))

    assert circles, "should detect the drawn circle"
    c = circles[0]
    assert c["shape_type"] == "circle"
    assert c["source"] == "circle"
    assert c["color_hex"].upper() == "#DD4F51"
    # centre (bbox is x,y,w,h with y measured from the bottom in TikZ)
    b = c["bbox_cm"]
    cx = b["x"] + b["w"] / 2
    assert abs(cx - 120) <= 6
    assert abs(b["w"] / 2 - 45) <= 8      # radius within a few px


def test_detects_concentric_bands():
    arr = _canvas()
    _disk(arr, 120, 120, 70, _TEAL)       # outer ring
    _disk(arr, 120, 120, 35, _WHITE)      # inner disk on top
    circles = _detect(arr, _palette(_TEAL, _WHITE))

    colors = {c["color_hex"].upper() for c in circles}
    assert "#4CB5B4" in colors, "outer teal ring missing"
    assert "#FDFEFD" in colors, "inner white disk missing"
    # the teal band must be the LARGER radius (drawn first, behind white)
    teal = max([c for c in circles if c["color_hex"].upper() == "#4CB5B4"],
               key=lambda c: c["bbox_cm"]["w"])
    white = max([c for c in circles if c["color_hex"].upper() == "#FDFEFD"],
                key=lambda c: c["bbox_cm"]["w"])
    assert teal["bbox_cm"]["w"] > white["bbox_cm"]["w"]


def test_rejects_empty_background():
    # A flat background has no circular edges → no phantom circles.
    assert _detect(_canvas(), _palette(_RED)) == []


def test_rejects_dense_tiling():
    # A frame blanketed with circles (op-art / pattern) is out of the discrete-
    # circle vocabulary; the coverage guard must bail out rather than stamp discs.
    arr = _canvas(240)
    for cy in range(30, 240, 45):
        for cx in range(30, 240, 45):
            _disk(arr, cx, cy, 26, _RED if (cx + cy) % 90 else _TEAL)
    assert _detect(arr, _palette(_RED, _TEAL)) == []


def test_empty_palette_returns_empty():
    assert ia._detect_circles(_canvas(), [], 240, 240, 240.0, 240.0) == []


# ─── Real-image functional test ───────────────────────────────────────────────

@pytest.mark.skipif(
    not (_ROOT / "capas_teste" / "capa_teste1.png").exists(),
    reason="capa_teste1.png not available",
)
def test_capa1_finds_concentric_motif():
    from PIL import Image
    arr = np.array(Image.open(_ROOT / "capas_teste" / "capa_teste1.png").convert("RGB"))
    h, w = arr.shape[:2]
    colors = ia._extract_colors(Image.fromarray(arr))
    circles = ia._detect_circles(arr, colors, w, h, 21.0, round(21.0 * h / w, 2))

    assert len(circles) >= 4, "capa1 has a concentric motif + discrete circles"
    # the concentric motif yields circles clearly larger than the small discrete
    # dots (~1cm); at least one ≥2cm-radius circle should sit in its footprint.
    big = [c for c in circles if c["bbox_cm"]["w"] / 2 >= 2.0]
    assert big, "the large concentric motif should be detected"
