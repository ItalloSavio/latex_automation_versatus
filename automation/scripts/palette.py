#!/usr/bin/env python3
"""
palette.py — a paleta k-means, separada dos detectores.

Ela vivia dentro de `image_analyzer.py`, e essa vizinhanca escondia uma dependencia
importante: das 20 capas, **18 usam so o `structural_reader`** e apenas capa1 e capa4 usam os
detectores de forma daquele modulo (grade, mosaico, circulos por Hough) — mas **as 20 dependem
dele mesmo assim**, porque e de la que sai a paleta com que o leitor quantiza. Foi por isso
que "apagar o image_analyzer" apareceu como refactor obvio varias vezes e teria quebrado tudo.

Com a paleta aqui, a dependencia real fica explicita e separavel: quem precisa so das cores
importa este arquivo, sem arrastar 1.800 linhas de deteccao de forma junto.

    from palette import extract_colors
    colors = extract_colors(Image.open(path))       # [{hex, rgb, coverage}, ...]

⚠️ O comportamento e IDENTICO ao que estava no `image_analyzer` — mesma miniatura, mesmo k,
mesma `random_state`. Isto e um MOVE, nao uma mudanca: qualquer alteracao de valor aqui muda
as 20 capas de uma vez, e passa pelo portao de regressao como qualquer outra.

⚠️ `_N_COLORS = 8` e fixo, e uma paleta adaptativa ja foi MEDIDA E REPROVADA (11/09): com
k=16 o leitor regride em todas as capas testadas (capa16 -0.030, capa8 -0.114, capa13 -0.027),
porque os clusters extras sao gastos em filme anti-serrilhado e viram pecas fantasma. Ver
"paleta adaptativa" no CLAUDE.md antes de mexer neste numero.
"""

try:
    import numpy as np
    from PIL import Image
    from sklearn.cluster import KMeans
    _OK = True
except ImportError:                                   # pragma: no cover
    _OK = False

# Miniatura para o k-means: a paleta de um poster nao depende de resolucao, e agrupar sobre a
# imagem inteira custa segundos sem mudar as cores.
_THUMB_W = 300
_THUMB_H = 450
_N_COLORS = 8


def extract_colors(img: "Image.Image", n_colors: int = _N_COLORS) -> "list[dict]":
    """K-means sobre uma miniatura. Devolve a lista ordenada por cobertura, maior primeiro."""
    thumb = img.resize((_THUMB_W, _THUMB_H), Image.LANCZOS)
    pixels = np.array(thumb).reshape(-1, 3).astype(float)

    km = KMeans(n_clusters=n_colors, n_init=10, random_state=42)
    km.fit(pixels)

    labels = km.labels_
    centers = km.cluster_centers_.round().astype(int)
    total = len(labels)

    colors = []
    for i, center in enumerate(centers):
        count = int(np.sum(labels == i))
        r, g, b = int(center[0]), int(center[1]), int(center[2])
        colors.append({
            "hex": f"#{r:02X}{g:02X}{b:02X}",
            "rgb": [r, g, b],
            "coverage": round(count / total, 4),
        })

    colors.sort(key=lambda c: c["coverage"], reverse=True)
    return colors
