#!/usr/bin/env python3
"""
ocr_extractor.py — OCR text extraction with bounding boxes in centimeters.

Uses EasyOCR (pip install easyocr) to detect and recognize text in cover
images, then normalizes all coordinates to centimeters so downstream modules
(cover_assembler, tikz_generator) work in a single unit.

EasyOCR was chosen over PaddleOCR because it supports Python 3.12+ and
installs purely via pip (no binary system tools, no CUDA required when
gpu=False).

Public API:
    extract_text(image_path, width_cm=21.0, height_cm=29.7) -> list[dict]

Each returned dict:
    text          str    — recognized text string
    bbox_cm       dict   — tight ink {x, y, w, h} in cm; y from bottom-left (TikZ)
    baseline_y_cm float  — TikZ y of the text baseline (for base-anchored nodes)
    font_size_pt  float  — em size in points, from ink height + vertical metrics
    stroke_ratio  float  — stroke-width ÷ em proxy (weight cue for font_matcher)
    confidence    float  — OCR confidence in [0, 1]
    color_hex     str    — estimated foreground (text) color, e.g. "#FFFFFF"

Returns [] silently when EasyOCR / numpy / Pillow are not installed.
"""

from pathlib import Path

# Swiss-design covers use clean, high-contrast type, so genuine text lines
# reliably score ≥ 0.5 while noise scores far lower. 0.50 (vs the old 0.60)
# recovers real secondary lines that EasyOCR rates just under 0.60 — e.g. a
# date/time footer line at ~0.59 — without admitting spurious detections.
_MIN_CONFIDENCE = 0.50   # a reading at or above this is kept outright
# Below it, keep a reading only when it is LONG. Measured over the eight text-heavy covers,
# confidence alone does not separate real captions from noise, but confidence + LENGTH does:
# between 0.20 and 0.45 everything real is long ('brooklyn tne shirts' 0.40, 'september 12 13,
# 74, 1975' 0.28, '315 bowery' 0.24, 'Material tecnico de formacso' 0.30) and everything
# spurious is 1-3 characters ('9' 0.39, '222' 0.23, '8' 0.21). Under 0.20 the noise gets long
# again — capa14's rotated type produces 20-30 character gibberish at 0.00-0.04 — so the floor
# stays. This recovers 8 real captions and admits none of the junk.
_WEAK_CONFIDENCE = 0.20  # nothing under this, at any length
_WEAK_MIN_CHARS  = 8     # alphanumeric characters required between _WEAK_ and _MIN_
_MIN_HEIGHT_CM  = 0.15   # drop sub-millimeter boxes (sensor noise / artifacts)
_CM_TO_PT       = 28.35  # typographic conversion

# EasyOCR quads run taller and wider than the ink they enclose, so a font size
# taken from the quad height overshoots and text renders too big. We instead
# measure the actual dark-ink bounding box inside the quad and convert its
# height to an em using Helvetica/Arial vertical metrics:
#   ascender ≈ 0.735·em, descender ≈ 0.21·em.
# Text with a descender glyph spans ascender→descender (≈0.945·em); text without
# spans ascender→baseline (≈0.735·em).
_ASCENDER_RATIO   = 0.735   # ink top → baseline, as a fraction of em
_ASC_DESC_RATIO   = 0.945   # ink top → descender bottom, as a fraction of em
_DESCENDER_CHARS  = set("gjpqy")
_DESCENDER_RATIO  = 0.21    # baseline → descender bottom, as a fraction of em

# Weight: median horizontal dark-run length ÷ ink height ≈ stroke-width / em.
# Helvetica regular stems land near 0.10, bold near 0.15+; 0.125 separates them.
_BOLD_STROKE_RATIO = 0.125
_INK_LUMA_THRESH   = 100    # pixels darker than this (0–255 luma) count as ink
# ── TINTA CLARA SOBRE FUNDO ESCURO ───────────────────────────────────────────────────────
# O medidor so procurava pixel ESCURO. Num titulo claro sobre fundo escuro os "escuros" sao o
# FUNDO, entao a caixa abraca a janela inteira em vez de apertar no glifo, e o corpo sai
# calculado a partir de uma altura que nao e a da letra.
#
# Medido nas 9 (2026-09-28): 19 de 73 elementos estao sobre fundo escuro, e a diferenca e
# grande — capa8 'the velvet' 55px medidos contra 38px reais (em de 79.6pt contra 54.0pt,
# 48% grande demais), 'underground' 66 -> 46, capa19 'the' 100 -> 75, capa1 'TéulodoLivro'
# 84 -> 62.
#
# ⚠️ Isto e a CAUSA dos dois ATENCAO do portao de aceite, e os dois estavam catalogados como
# outra coisa: o `_select_text` apaga o titulo da capa8 (`SEM=0.9311 > COM=0.9280`) porque
# desenha-lo 48% grande e pior que nao desenhar — e o retraco depois o quebra em poligonos,
# o que a fila chamava de "teto do tracado"; e o titulo da capa1 "sai maior, com entrelinha
# larga", catalogado como A11.
#
# O `snap_text_adds` ja era DIRECAO-CIENTE desde 03/08; o medidor do OCR nunca foi.
# A peca entra AO LADO do caminho velho: fundo claro segue no limiar absoluto, verbatim.
_INK_DARK_BG      = 110    # mediana da BORDA abaixo disto = fundo escuro
_INK_REL_DELTA    = 55     # distancia ao fundo para o pixel contar como tinta (mesmo 55 do snap)

# -- A caixa nao pode ser mais alta que o PASSO do proprio paragrafo -----------------------
# O quad do EasyOCR e frouxo na vertical: numa coluna de texto corrido ele frequentemente
# inclui os DESCENDENTES da linha de cima, e como o _measure_ink procura tinta DENTRO do
# quad, essa tinta alheia entra na caixa. O erro e invisivel em baixa resolucao e salta aos
# olhos quando ha pixel: medido no poster de 1728px (2026-09-23), um unico paragrafo
# uniforme deu alturas de 22, 23, 28, 29, 29, 42, 43 e 48px enquanto o PASSO entre as linhas
# se manteve constante em ~33px. As tres caixas acima do passo invadiam a linha de cima em
# 4-11px, e o render empilhava as linhas umas sobre as outras.
#
# A invariante e barata e local: num paragrafo nenhuma caixa e mais alta que o passo, e o
# passo se mede nas vizinhas. So a BASE e confiavel (a contaminacao entra por CIMA), entao a
# correcao recorta o topo e re-mede a tinta na banda restante.
_PITCH_MIN_LINES = 3     # sem 3 linhas nao ha passo: uma reta por 2 pontos nao decide nada
# ⚠️ A primeira versao comparava a altura da caixa com o PASSO, e estava ERRADA: medido, a
# coluna esquerda do poster tem tinta de ~40px com passo de 34px — entrelinha mais apertada
# que a tinta e composicao normal —, e a regra acusou 9 de 10 linhas SAS. O discriminador
# certo e ser OUTLIER dentro do proprio paragrafo, e o limiar sai da tipografia em vez de
# ajuste: entre duas linhas do MESMO corpo, a maior razao legitima e ascendente+descendente
# sobre ascendente-so = 0.945/0.735 = 1.29. Acima disso a caixa contem tinta que nao e dela.
_PITCH_TOL       = 1.35  # margem pequena sobre o maximo tipografico de 1.29
_PITCH_LEFT_TOL  = 0.02  # fracao da LARGURA: quao alinhadas em X duas linhas do mesmo bloco
_PITCH_GAP_MAX   = 3.0   # salto vertical maximo, em alturas de linha, antes de quebrar o bloco
_PITCH_SIZE_RAT  = 1.6   # um paragrafo tem CORPO uniforme: linha muito maior/menor quebra o bloco
_PITCH_SPREAD    = 0.25  # passo irregular (>25% de dispersao) = nao e paragrafo; nao mexe
# ⚠️ PISO DE RESOLUCAO, achado pelo A/B isolado nas 3 capas afetadas (2026-09-25).
# Medido, com os dois lados na mao: capa19 ZERO diferenca (o VLM sobrescreve o elemento de
# qualquer jeito), capa8 um unico elemento a 13.53->13.43pt (0.7%, invisivel) e capa12 os
# quatro nomes do elenco — onde a regra PIOROU, no olho e no numero (0.9588 -> 0.9579): no
# original os cinco tem o mesmo corpo, sem a regra ficam quase uniformes, e COM ela
# 'david schwimmer' salta maior e 'matthew perry' encolhe.
# A causa e que aqueles nomes tem 7-10px de linha: a regra estava inferindo "paragrafo" a
# partir de medicao que nao existe. Ela precisa da propria pre-condicao, e o piso e o MESMO
# que o `accept.word_collisions` ja usa e que o estagio de aviso mede — abaixo de 16px a
# leitura nao e confiavel. E a regra da capa5: quando nao da pra medir, NAO CHUTE.
# Efeito: inerte nas 9 do MVP (todas abaixo do piso), ativa nos posteres em alta, onde
# conserta 3 caixas genuinamente contaminadas.
_PITCH_MIN_LINE_PX = 16

# ── A REGUA DA GRADE VIRA LETRA FANTASMA NA LEITURA ──────────────────────────────────────
# Medido no poster de 1728px (2026-09-28): ha uma linha vertical de 2px em x=118-119 com 100%
# de cobertura ao longo de toda a coluna de texto, e as caixas do OCR comecam em x=117 — a
# regua fica DENTRO da caixa. O EasyOCR a le como glifo e devolve 'Jadipiscing', 'Iod tempor',
# 'Meniam', 'Itation', 'Jut aliquip', 'kconsequat', 'ITIPOGRAFIA'. Sete das 31 linhas.
#
# ⚠️ Duas medicoes derrubaram consertos mais simples antes deste:
#   (a) "ha tinta a ESQUERDA da caixa" — nao ha: 0% nos dois grupos, porque o _measure_ink ja
#       encolheu a caixa ATE a regua, entao ela esta a direita de x0, dentro;
#   (b) "a regua distingue linha fantasma de linha limpa" — NAO distingue: ela atravessa a
#       coluna inteira, entao aparece em 100% das linhas, fantasma ou nao. Cortar o primeiro
#       caractere transformaria 'Dolor' em 'olor'.
# O que resta e tirar a regua da ENTRADA do OCR — nao da imagem de comparacao, que continua
# sendo o gabarito. E a mesma divisao que o mapa de layout ja faz mascarando caixas de texto
# antes da projecao Sobel.
#
# ⚠️ A classe e ZERO nas 9 capas do MVP e 7/31 no poster: ela CHEGA COM A RESOLUCAO, porque a
# regua so fica grossa o bastante para virar glifo acima de ~150 dpi.
# ⚠️ PISO DE RESOLUCAO, e ele foi achado por REGRESSAO. Sem ele a mascara DESTROI texto nas
# capas em baixa: capa6 perdeu 3 dos 4 elementos, capa8 virou "upstairs at max's I==== city",
# capa2 truncou 'Versatus HPC Technical Bock' para 'Versatus HPC Tane'. A causa e a mesma da
# regra de paragrafo: a 56-89 dpi a HASTE DE UMA LETRA tambem tem 1-2px, e a sonda de 4px nao
# consegue separar haste de regua. Acima de ~150 dpi a haste engorda e a separacao volta.
# As 9 do MVP estao em 56-89 dpi e o poster em 209 — 1.7x de folga para cada lado.
_RULE_MIN_DPI     = 150    # abaixo disto a mascara NAO roda: nao da para separar, entao nao chuta
_RULE_MAX_W       = 3      # px — mais largo que isto e desenho, nao regua
_RULE_MIN_LEN     = 0.04   # fracao da dimensao: uma regua e LONGA
_RULE_UNIFORM     = 12.0   # desvio maximo ao longo da regua para ela contar como uma linha
_RULE_CONTRAST    = 40.0   # distancia minima ao que ha dos DOIS lados


# ─── Public entry point ───────────────────────────────────────────────────────

def extract_text(
    image_path: "str | Path",
    width_cm:   float = 21.0,
    height_cm:  float = 29.7,
) -> "list[dict]":
    """
    Extract text elements from a cover image using PaddleOCR.

    Parameters
    ----------
    image_path : path to image (PNG / JPEG / WEBP)
    width_cm   : physical width in cm  (default: A4 portrait = 21 cm)
    height_cm  : physical height in cm (default: A4 portrait = 29.7 cm)

    Returns
    -------
    list of text-element dicts, sorted top-to-bottom then left-to-right.
    Empty list if PaddleOCR is unavailable or no text is found.
    """
    try:
        return _run_ocr(Path(image_path).resolve(), width_cm, height_cm)
    except Exception as exc:
        _s = str(exc)
        if "No module named" in _s or "ModuleNotFoundError" in type(exc).__name__:
            return []
        print(f"    [OCR] Aviso: extracao falhou ({type(exc).__name__}: {_s[:120]})")
        return []


# ─── Core OCR pipeline ────────────────────────────────────────────────────────

def _run_ocr(path: Path, width_cm: float, height_cm: float) -> "list[dict]":
    import easyocr          # noqa: PLC0415
    import numpy as np      # noqa: PLC0415
    from PIL import Image   # noqa: PLC0415

    img  = Image.open(path).convert("RGB")
    w_px = img.width
    h_px = img.height
    arr  = np.array(img)
    gray = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]

    # EasyOCR: gpu=False → CPU-only, no CUDA required.
    # ['en', 'pt'] covers both English and Portuguese text found on covers.
    # verbose=False suppresses download-progress and inference spam.
    # width_ths=0.8 (default 0.5) lets EasyOCR join fragments across a wider gap,
    # so a single line broken by a separator ("65p in advance / 75p at the door")
    # is read as one string with the "/" instead of two boxes that drop it.
    reader = easyocr.Reader(["en", "pt"], gpu=False, verbose=False)

    # TRIED AND REVERTED (2026-09-11): running DETECTION on a 3x Lanczos upscale while
    # measuring ink natively. The recall is real — capa16 went 8 -> 9 elements, recovering
    # "saturday" and "7 pm sharp" whole and completing "only $6 / all ages", and capa8 finally
    # READ "the velvet" instead of leaving it to be traced as blob-glyphs. It still made
    # capa8 worse, for three reasons that all live DOWNSTREAM of here:
    #   · the extra detections arrive FRAGMENTED ("/11", "pm", "& 1 am" as three boxes) and
    #     render on top of the line below;
    #   · the looser quad makes _measure_ink catch more than the glyph, so the captions came
    #     out 18.5pt against the 14.6pt they measure natively — type visibly too large;
    #   · "the velvet" was read and then DROPPED by the Score-driven text gate, while the
    #     reader had already masked those pixels because the OCR claimed them — so the title
    #     lost both its text and its traced fallback and left a hole.
    # Score 0.9386 -> 0.9279 and the eye agrees it is worse. Re-attempt only after the text
    # gate stops deleting legitimate lines and fragments are re-joined.
    # ⚠️ SEMPRE um CAMINHO, nunca o array. Medido (2026-09-28): com a mascara INERTE (0 px
    # alterados), trocar `readtext(path)` por `readtext(array)` sozinho derruba a capa6 de 4
    # para 1 elemento, quebra strings da capa2 e come o acento de 'RASCUNHO TÉCNICO' — o
    # EasyOCR pre-processa os dois caminhos de forma diferente. Eu havia atribuido esse dano
    # a mascara; era a troca de entrada.
    result = reader.readtext(_ocr_input_path(path, arr), width_ths=0.8)
    scale = 1

    elements: list[dict] = []
    if not result:
        return elements

    # EasyOCR result format: [(quad, text, confidence), ...]
    for quad, text, conf in result:
        text = text.strip()
        if not text:
            continue
        if conf < _MIN_CONFIDENCE:
            n_alnum = sum(ch.isalnum() for ch in text)
            if conf < _WEAK_CONFIDENCE or n_alnum < _WEAK_MIN_CHARS:
                continue

        # Convert 4-corner quad to axis-aligned pixel bbox
        xs = [p[0] / scale for p in quad]
        ys = [p[1] / scale for p in quad]
        x1, y1 = int(min(xs)), int(min(ys))
        x2, y2 = int(max(xs)), int(max(ys))

        # Tighten the loose OCR quad to the actual ink it encloses. Everything
        # downstream (size, position, weight) keys off these ink pixels.
        ink = _measure_ink(gray[y1:y2, x1:x2])
        if ink is None:
            continue
        ix0, iy0, ix1, iy1, stroke_ratio = ink
        px0, py0, px1, py1 = x1 + ix0, y1 + iy0, x1 + ix1, y1 + iy1

        ink_h_px = py1 - py0
        h_box_cm = ink_h_px / h_px * height_cm
        if h_box_cm < _MIN_HEIGHT_CM:
            continue
        w_box_cm = (px1 - px0) / w_px * width_cm

        # Em height from ink height, accounting for whether a descender is present.
        has_desc = any(c in _DESCENDER_CHARS for c in text.lower())
        em_ratio = _ASC_DESC_RATIO if has_desc else _ASCENDER_RATIO
        em_px    = ink_h_px / em_ratio
        font_pt  = em_px / h_px * height_cm * _CM_TO_PT

        # Baseline sits a descender's depth above the ink bottom (or at it when
        # there is no descender). TikZ y grows upward from the bottom edge.
        desc_px     = (em_px * _DESCENDER_RATIO) if has_desc else 0.0
        baseline_px = py1 - desc_px
        x_cm        = px0 / w_px * width_cm
        y_cm        = (h_px - py1) / h_px * height_cm            # ink bottom
        baseline_cm = (h_px - baseline_px) / h_px * height_cm

        roi       = arr[py0:py1, px0:px1]
        color_hex = _estimate_text_color(roi)

        elements.append({
            "text":         text,
            "bbox_cm":      {
                "x": round(x_cm,     3),
                "y": round(y_cm,     3),
                "w": round(w_box_cm, 3),
                "h": round(h_box_cm, 3),
            },
            "baseline_y_cm": round(baseline_cm, 3),
            "font_size_pt":  round(font_pt, 1),
            "stroke_ratio":  round(stroke_ratio, 3),
            "confidence":    round(conf, 3),
            "color_hex":     color_hex,
            "_px":           (px0, py0, px1, py1),   # temporario: ver _cap_to_line_pitch
        })

    _cap_to_line_pitch(elements, gray, arr, w_px, h_px, width_cm, height_cm)
    for e in elements:
        e.pop("_px", None)

    # Sort top-to-bottom (descending TikZ y), then left-to-right
    elements.sort(key=lambda e: (-e["bbox_cm"]["y"], e["bbox_cm"]["x"]))
    return elements


def _paragraphs(elements: "list[dict]", w_px: int) -> "list[list[dict]]":
    """Agrupa linhas de um mesmo BLOCO de texto: alinhadas a esquerda e verticalmente seguidas.

    ⚠️ A primeira versao agrupava por sobreposicao em X contra a extensao ACUMULADA da coluna.
    Medido no poster: o titulo 'design' e largo, entra no grupo, a coluna herda a largura dele
    e passa a engolir a pagina — 30 das 31 linhas num grupo so. Um paragrafo se reconhece pela
    MARGEM ESQUERDA, que e a mesma linha a linha, nao por area compartilhada.
    """
    tol = _PITCH_LEFT_TOL * w_px
    blocos: list[list[dict]] = []
    for el in sorted(elements, key=lambda e: e["_px"][3]):      # por BASE da tinta, de cima p/ baixo
        x0, y0, _, y1 = el["_px"]
        alt = max(y1 - y0, 1)
        for b in blocos:
            lx0, ly0, _, ly1 = b[-1]["_px"]
            lalt = max(ly1 - ly0, 1)
            if (abs(x0 - lx0) <= tol
                    and 0 < (y1 - ly1) <= _PITCH_GAP_MAX * max(alt, lalt)
                    and (1 / _PITCH_SIZE_RAT) <= alt / lalt <= _PITCH_SIZE_RAT):
                b.append(el)
                break
        else:
            blocos.append([el])
    return blocos


def _cap_to_line_pitch(elements, gray, arr, w_px, h_px, width_cm, height_cm) -> None:
    """Recorta o TOPO da caixa que passa do passo do paragrafo e re-mede a tinta.

    Age no lugar. Ver o bloco de constantes para a medicao que motivou a regra.
    """
    for col in _paragraphs(elements, w_px):
        if len(col) < _PITCH_MIN_LINES:
            continue
        passos = [col[i + 1]["_px"][3] - col[i]["_px"][3] for i in range(len(col) - 1)]
        passos = [p for p in passos if p > 0]
        if len(passos) < _PITCH_MIN_LINES - 1:
            continue
        passos.sort()
        pitch = passos[len(passos) // 2]
        # passo irregular nao descreve um paragrafo — nao ha invariante para aplicar
        disp = sum(abs(p - pitch) for p in passos) / (len(passos) * max(pitch, 1))
        if pitch <= 0 or disp > _PITCH_SPREAD:
            continue

        # a regua e a ALTURA MEDIANA do proprio paragrafo, nao o passo (ver _PITCH_TOL)
        alturas = sorted(e["_px"][3] - e["_px"][1] for e in col)
        alvo = alturas[len(alturas) // 2]
        # abaixo do piso de resolucao nao ha medicao para sustentar a regra (ver _PITCH_MIN_LINE_PX)
        if alvo < _PITCH_MIN_LINE_PX:
            continue
        if alvo <= 0:
            continue

        for el in col:
            px0, py0, px1, py1 = el["_px"]
            if (py1 - py0) <= alvo * _PITCH_TOL:
                continue
            novo_py0 = max(0, py1 - alvo)
            ink = _measure_ink(gray[novo_py0:py1, px0:px1])
            if ink is None:
                continue
            ix0, iy0, ix1, iy1, stroke_ratio = ink
            qx0, qy0, qx1, qy1 = px0 + ix0, novo_py0 + iy0, px0 + ix1, novo_py0 + iy1
            ink_h_px = qy1 - qy0
            if ink_h_px <= 0 or (ink_h_px / h_px * height_cm) < _MIN_HEIGHT_CM:
                continue

            has_desc = any(c in _DESCENDER_CHARS for c in el["text"].lower())
            em_px    = ink_h_px / (_ASC_DESC_RATIO if has_desc else _ASCENDER_RATIO)
            desc_px  = (em_px * _DESCENDER_RATIO) if has_desc else 0.0

            el["bbox_cm"] = {
                "x": round(qx0 / w_px * width_cm, 3),
                "y": round((h_px - qy1) / h_px * height_cm, 3),
                "w": round((qx1 - qx0) / w_px * width_cm, 3),
                "h": round(ink_h_px / h_px * height_cm, 3),
            }
            el["baseline_y_cm"] = round((h_px - (qy1 - desc_px)) / h_px * height_cm, 3)
            el["font_size_pt"]  = round(em_px / h_px * height_cm * _CM_TO_PT, 1)
            el["stroke_ratio"]  = round(stroke_ratio, 3)
            el["color_hex"]     = _estimate_text_color(arr[qy0:qy1, qx0:qx1])
            el["_px"]           = (qx0, qy0, qx1, qy1)

        _uniform_body(col)


def _uniform_body(col: "list[dict]") -> None:
    """Num paragrafo o CORPO e o mesmo em todas as linhas: use a mediana do bloco.

    O em sai de `ink / ratio`, e o `ratio` e escolhido por LINHA conforme ela tenha ou nao
    descendente (0.735 vs 0.945). Medido no poster de 1728px (2026-09-23), as duas leituras
    nao convergem para o mesmo em: no MESMO paragrafo, 'Dolor sit amet, consectetur' (sem
    descendente) sai a 18.7pt e 'labore et dolore magna' a 15.3pt, 22% de diferenca onde o
    desenho tem zero. A altura da tinta e ruidosa em +-1px e a razao amplifica esse ruido; a
    mediana do bloco nao.

    Mesmo principio que o `edit_gate` ja aplica no snap por bandas ("fonte pela mediana do
    bloco: no Swiss o header difere em PESO, nao em tamanho"). So age com >= _PITCH_MIN_LINES.
    """
    if len(col) < _PITCH_MIN_LINES:
        return
    pts = sorted(e["font_size_pt"] for e in col if e.get("font_size_pt"))
    if not pts or pts[0] <= 0:
        return
    # ⚠️ Guard achado por REGRESSAO nas 9 (2026-09-23). Sem ele a regra unificava blocos que
    # NAO sao paragrafos — linhas de imprint soltas que por acaso partilham margem esquerda e
    # ficam perto: capa1 'DATA: 12 de junho' 16.4 -> 21.0pt e 'VERSAO: v0.1' 24.0 -> 21.0pt,
    # capa13 'AtomGlide Essentials' 7.7 -> 12.0pt, capa8 'held over...' 19.9 -> 15.5pt,
    # capa19 'the' 174.2 -> 135.5pt. Quatro capas entregues alteradas por uma regra que so
    # deveria remover RUIDO.
    # O criterio sai da mesma tipografia que justifica _PITCH_TOL: se o bloco fosse um corpo
    # so, a divergencia entre suas linhas nao passaria de 0.945/0.735 = 1.29. Acima disso as
    # linhas tem tamanhos DIFERENTES de propria, e nao ha o que unificar.
    if pts[-1] / pts[0] > _PITCH_TOL:
        return
    alvo = pts[len(pts) // 2]
    for e in col:
        e["font_size_pt"] = alvo


def _ocr_input_path(path: Path, arr) -> str:
    """O caminho que o OCR deve ler: o original, ou uma copia sem as reguas quando ha o que tirar."""
    try:
        import numpy as np                                        # noqa: PLC0415
        from PIL import Image as _Im                              # noqa: PLC0415
    except Exception:
        return str(path)
    m = _mask_rules(arr)
    if not np.any(np.abs(m.astype(float) - arr).sum(axis=2) > 10):
        return str(path)                                          # nada a mascarar: intocado
    try:
        import tempfile                                           # noqa: PLC0415
        tmp = Path(tempfile.gettempdir()) / f"_ocr_sem_reguas_{path.stem}.png"
        _Im.fromarray(m).save(tmp)
        return str(tmp)
    except Exception:
        return str(path)


def _mask_rules(arr):
    """Devolve uma COPIA da imagem com as reguas finas pintadas com o que ha ao lado.

    So a ENTRADA do OCR muda; a imagem original segue intocada como gabarito.

    ⚠️ A primeira versao exigia a COLUNA INTEIRA uniforme e nao disparava nunca: medido, a
    regua do poster cobre 89% da coluna (corrida continua de 2204px de 2464), entao o desvio
    da coluna toda da 49.7 contra um limiar de 12. O teste certo e por CORRIDA.

    Um pixel e "fino" quando difere dos dois lados a `_RULE_MAX_W+1` px de distancia; uma
    REGUA e uma corrida longa de pixels finos. A haste de uma letra tambem e fina, mas sua
    corrida tem a altura do glifo (~30px), nao 25% da pagina — e o comprimento que separa.
    """
    try:
        import numpy as np                                        # noqa: PLC0415
    except Exception:
        return arr.astype("uint8") if hasattr(arr, "astype") else arr

    out = np.array(arr, dtype=float, copy=True)
    h, w, _ = out.shape
    # abaixo do piso a sonda nao separa haste de regua (ver _RULE_MIN_DPI)
    if w / (21.0 / 2.54) < _RULE_MIN_DPI:
        return out.astype("uint8")
    d = _RULE_MAX_W + 1

    for eixo in (0, 1):                       # 0 = reguas VERTICAIS, 1 = HORIZONTAIS
        n_len = h if eixo == 0 else w         # comprimento ao longo da regua
        minrun = max(8, int(_RULE_MIN_LEN * n_len))
        A = out if eixo == 0 else out.transpose(1, 0, 2)   # sempre "regua corre no eixo 0"
        H, Wd, _ = A.shape
        if Wd <= 2 * d:
            continue
        esq, dir_ = A[:, :-2 * d, :], A[:, 2 * d:, :]
        meio = A[:, d:-d, :]
        fino = ((np.abs(meio - esq).max(axis=2) >= _RULE_CONTRAST)
                & (np.abs(meio - dir_).max(axis=2) >= _RULE_CONTRAST))
        for j in range(fino.shape[1]):
            col = fino[:, j]
            if not col.any():
                continue
            # corridas continuas de pixel fino
            idx = np.flatnonzero(np.diff(np.r_[0, col.view(np.int8), 0]))
            for a, b in zip(idx[::2], idx[1::2]):
                if b - a < minrun:
                    continue
                x = j + d
                novo = (A[a:b, x - d, :] + A[a:b, x + d, :]) / 2.0
                for k in range(-(_RULE_MAX_W // 2), _RULE_MAX_W // 2 + 1):
                    xx = x + k
                    if 0 <= xx < Wd:
                        A[a:b, xx, :] = novo
        if eixo == 1:
            out = A.transpose(1, 0, 2)
        else:
            out = A
    return out.astype("uint8")


# ─── Ink geometry ─────────────────────────────────────────────────────────────

def _measure_ink(gray_roi: "np.ndarray") -> "tuple[int,int,int,int,float] | None":
    """
    Find the tight dark-ink bounding box inside a (loose) OCR quad.

    Returns (x0, y0, x1, y1, stroke_ratio) in ROI-local pixel coordinates, where
    stroke_ratio = median horizontal dark-run length ÷ ink height (a scale-free
    proxy for stroke weight). Returns None when the ROI holds no ink.
    """
    import numpy as np  # noqa: PLC0415

    if gray_roi.size == 0:
        return None
    mask = _ink_mask(gray_roi, np)
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return None
    y0, y1 = int(rows[0]), int(rows[-1]) + 1
    x0, x1 = int(cols[0]), int(cols[-1]) + 1

    ink_h = max(y1 - y0, 1)
    runs  = _dark_run_lengths(mask[y0:y1, x0:x1])
    stroke_ratio = (float(np.median(runs)) / ink_h) if runs else 0.0
    return x0, y0, x1, y1, stroke_ratio


def _ink_mask(gray_roi, np):
    """A mascara de TINTA, ciente da polaridade. Ver o bloco de constantes."""
    if gray_roi.shape[0] < 2 or gray_roi.shape[1] < 2:
        return gray_roi < _INK_LUMA_THRESH
    borda = np.concatenate([gray_roi[0, :], gray_roi[-1, :],
                            gray_roi[:, 0], gray_roi[:, -1]])
    if float(np.median(borda)) < _INK_DARK_BG:          # fundo ESCURO -> tinta CLARA
        m = gray_roi > float(np.median(borda)) + _INK_REL_DELTA
        if m.any():
            return m
    return gray_roi < _INK_LUMA_THRESH                  # caminho velho, verbatim


def _dark_run_lengths(mask: "np.ndarray") -> "list[int]":
    """Lengths of every horizontal run of True pixels (stroke-width samples)."""
    runs: list[int] = []
    for row in mask:
        count = 0
        for v in row:
            if v:
                count += 1
            elif count:
                runs.append(count)
                count = 0
        if count:
            runs.append(count)
    return runs


# ─── Text color estimation ────────────────────────────────────────────────────

def _estimate_text_color(roi: "np.ndarray") -> str:
    """
    Estimate the foreground (text) color from a cropped ink region.

    Strategy: 2-cluster K-means, then take the MINORITY cluster as the text.
    Within a tight ink box the glyph strokes always cover less area than the
    surrounding background, so the smaller cluster is the ink regardless of
    whether the text is dark-on-light or light-on-dark. (The old luminance
    heuristic misfired when the two cluster centres averaged near mid-grey,
    picking the background and washing near-black text out to a mid charcoal.)
    Falls back to #000000 when the region is too small or sklearn is absent.
    """
    try:
        import numpy as np                  # noqa: PLC0415
        from sklearn.cluster import KMeans  # noqa: PLC0415

        pixels = roi.reshape(-1, 3).astype(float)
        if len(pixels) < 10:
            return "#000000"

        km       = KMeans(n_clusters=2, n_init=3, random_state=0).fit(pixels)
        counts   = np.bincount(km.labels_, minlength=2)
        ink_i    = int(np.argmin(counts))
        ground   = km.cluster_centers_[1 - ink_i]
        ink      = pixels[km.labels_ == ink_i]

        # The CORE of the stroke, not the average of everything the ink cluster caught.
        # That cluster holds the glyph core AND its anti-aliased rim, and at these source
        # resolutions (a 570px-wide poster, type 6-14px tall) the rim is most of the pixels,
        # so the centroid drifts toward the ground: capa8's white captions were measured
        # #9B9C9F where the brightest 5% of the ink is #C8C9CB and the design colour is the
        # palette's #DFE0D5 — white type rendering as mid-grey. Keeping the third of the ink
        # FURTHEST from the ground recovers the real colour. Same instrument that
        # _find_span_cut already uses per column; this is the general path finally using it.
        text_rgb = ground if not len(ink) else ink.mean(axis=0)
        if len(ink) >= 6:
            far = np.linalg.norm(ink - ground, axis=1)
            core = ink[far >= np.percentile(far, 70)]
            if len(core):
                text_rgb = core.mean(axis=0)

        r = max(0, min(255, int(round(text_rgb[0]))))
        g = max(0, min(255, int(round(text_rgb[1]))))
        b = max(0, min(255, int(round(text_rgb[2]))))
        return f"#{r:02X}{g:02X}{b:02X}"

    except Exception:
        return "#000000"



# ─── Colour per span (A4) ─────────────────────────────────────────────────────

_SPAN_GAP_MIN  = 150.0   # RGB distance between the two halves' ink before we split at all
_SPAN_SIDE_MIN = 0.25    # each side must own this fraction of the inked columns
_SPAN_INK_MIN  = 60.0    # a pixel is ink when it is this far from ITS OWN column background
# A column whose "ink" fills the whole box is not ink — the per-column background estimate
# failed there. It fails exactly where the box ABUTS another region: capa8's "underground"
# sits right on top of the orange half-disc, so `bg` is the median of black-above and
# orange-below and comes out ORANGE, which makes the real black ground register as ink at
# full column height. The measured ink is then #000009 on those columns and #DFE1DE on the
# honest ones — a 240 RGB gap that clears _SPAN_GAP_MIN and splits a word whose ink is
# uniform (#DEE0D9..#DFE2DB across 8 column bands, under 2 points of luminance).
# This is the SAME failure the per-column sampling was introduced to avoid; it just moved
# from the whole box to the boundary columns.
# Measured separation on the four candidates: fraction of columns above 0.85 is
#   capa8 "underground" 62% (FALSE) · capa17 "SWISS" 25% · capa19 "theshining" 2% (TRUE).
_SPAN_INK_MAX_FRAC = 0.85
_SPAN_ROW_FRAC = 0.18   # share of the span a row must span to count as a line of type


def split_bicolour_text(elements: list, image_path, width_cm: float, height_cm: float) -> list:
    """Split one OCR element into two when its ink genuinely changes colour along x.

    EasyOCR hands back one box with one colour, so a title that crosses two regions gets a
    single ink colour and half of it goes invisible: capa19's "theshining" is light over the
    black shape and dark over the yellow, and painting it all #2B2A25 erases "the".

    The background is sampled PER COLUMN, from just above and below the box. That matters:
    a 2-cluster KMeans over the whole box separates the two BACKGROUNDS, not ink from
    background, so it is blind precisely here — an earlier attempt using it reported zero
    bicolour elements on the very covers that have them. Sampling one point under the centre
    fails for the same reason (capa17's "SWISS" has its centre in a black bar while the word
    lies on white), which is why that guard was reverted.

    Measured on the 20 covers: 3 of 140 elements clear both guards (capa8 "underground",
    capa17 "SWISS", capa19 "theshining") and the cut lands on the word boundary — 33% of
    "theshining" is exactly "the". The other 137 are returned untouched.
    """
    try:
        import numpy as np                 # noqa: PLC0415
        from PIL import Image              # noqa: PLC0415
    except Exception:
        return elements

    try:
        arr = np.asarray(Image.open(image_path).convert("RGB")).astype(float)
    except Exception:
        return elements
    h_px, w_px = arr.shape[:2]

    out = []
    for el in elements:
        split = _find_span_cut(arr, el, width_cm, height_cm, w_px, h_px)
        if split is None:
            out.append(el)
            continue
        frac, hex1, hex2 = split
        b = el["bbox_cm"]
        ncut = max(1, min(len(el["text"]) - 1, round(frac * len(el["text"]))))
        for text, x, w, hexc in (
            (el["text"][:ncut], b["x"],                 b["w"] * frac,       hex1),
            (el["text"][ncut:], b["x"] + b["w"] * frac, b["w"] * (1 - frac), hex2),
        ):
            part = dict(el)
            part["text"] = text
            part["bbox_cm"] = {"x": round(x, 3), "y": b["y"],
                               "w": round(w, 3), "h": b["h"]}
            part["color_hex"] = hexc
            out.append(part)
    return out


def _find_span_cut(arr, el, width_cm, height_cm, w_px, h_px):
    """Return (cut_fraction, left_hex, right_hex) when the ink is genuinely two-coloured."""
    import numpy as np  # noqa: PLC0415

    b = el.get("bbox_cm") or {}
    try:
        x0 = int(b["x"] / width_cm * w_px)
        x1 = int((b["x"] + b["w"]) / width_cm * w_px)
        y1 = int((height_cm - b["y"]) / height_cm * h_px)
        y0 = int(y1 - b["h"] / height_cm * h_px)
    except Exception:
        return None
    x0, x1 = max(0, x0), min(w_px, x1)
    y0, y1 = max(0, y0), min(h_px, y1)
    if x1 - x0 < 12 or y1 - y0 < 4:
        return None

    pad  = max(2, int((y1 - y0) * 0.35))
    cols = []
    for x in range(x0, x1):
        ctx = [c for c in (arr[max(0, y0 - pad):y0, x], arr[y1:min(h_px, y1 + pad), x]) if len(c)]
        if not ctx:
            continue
        bg  = np.median(np.vstack(ctx), axis=0)
        col = arr[y0:y1, x]
        d   = np.linalg.norm(col - bg, axis=1)
        ink = col[d > _SPAN_INK_MIN]
        # Ink that spans the full column height is a failed background estimate, not a
        # letterform: drop the column rather than let its colour vote. See _SPAN_INK_MAX_FRAC.
        if len(ink) > (y1 - y0) * _SPAN_INK_MAX_FRAC:
            continue
        if len(ink) >= 2:
            # The CORE of the stroke, not its average. Averaging every inked pixel folds in
            # the anti-aliased rim, which is a blend of ink and ground, and the result drifts
            # toward the background: capa19's near-black "shining" came out #4F4925 (a muddy
            # olive) and its white "the" came out #DCDAC7. Both read as washed out and the
            # Score fell even though the split itself was right. Keeping the pixels FURTHEST
            # from the ground recovers the true ink.
            dk = d[d > _SPAN_INK_MIN]
            core = ink[dk >= np.percentile(dk, 70)]
            cols.append((core if len(core) else ink).mean(axis=0))
    if len(cols) < 12:
        return None

    lo   = max(1, int(len(cols) * _SPAN_SIDE_MIN))
    best = (0.0, None)
    for i in range(lo, len(cols) - lo):
        c1 = np.mean(cols[:i], axis=0)
        c2 = np.mean(cols[i:], axis=0)
        d  = float(np.linalg.norm(c1 - c2))
        if d > best[0]:
            best = (d, (i / len(cols), c1, c2))
    if best[0] < _SPAN_GAP_MIN:
        return None
    frac, c1, c2 = best[1]
    return frac, _rgb_hex(c1), _rgb_hex(c2)


def _rgb_hex(c) -> str:
    r, g, b = (max(0, min(255, int(round(v)))) for v in c[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    _usage = (
        f"Uso: python {Path(__file__).name} <imagem> [width_cm] [height_cm]\n\n"
        "Extrai texto da imagem e imprime os elementos em JSON.\n\n"
        "Exemplos:\n"
        "  python ocr_extractor.py capa_teste4.png\n"
        "  python ocr_extractor.py capa.png 21.0 29.7\n\n"
        "Dependencias:\n"
        "  pip install easyocr Pillow numpy scikit-learn"
    )

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(_usage)
        sys.exit(0)

    _path    = sys.argv[1]
    _wcm     = float(sys.argv[2]) if len(sys.argv) > 2 else 21.0
    _hcm     = float(sys.argv[3]) if len(sys.argv) > 3 else 29.7

    print(f"[OCR] Processando: {_path}  ({_wcm} × {_hcm} cm)")
    _result = extract_text(_path, _wcm, _hcm)

    if not _result:
        print("\nNenhum texto detectado (ou EasyOCR nao instalado).")
        print("Instale com:  pip install easyocr")
        sys.exit(0)

    print(f"\n{len(_result)} elemento(s) detectado(s):\n")
    print(json.dumps(_result, ensure_ascii=False, indent=2))

    print("\n--- Resumo ---")
    for el in _result:
        bx = el["bbox_cm"]
        print(
            f"  {el['text']!r:30s}  "
            f"pos=({bx['x']:.2f}, {bx['y']:.2f})cm  "
            f"h={bx['h']:.2f}cm  "
            f"~{el['font_size_pt']}pt  "
            f"conf={el['confidence']:.2f}  "
            f"cor={el['color_hex']}"
        )
