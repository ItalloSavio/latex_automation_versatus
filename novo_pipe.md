# Swiss Cover Replicator — Pipeline Técnico

Documento vivo. Atualizado a cada ciclo de mudanças.

---

## O que o sistema faz

Recebe uma imagem PNG de uma capa e gera um PDF replicado via TikZ/LuaLaTeX.
Sem VLM no modo padrão (`--local`); toda a análise é CV + heurísticas.

---

## Pipeline (10 estágios)

| # | Estágio | Arquivo | Ferramenta principal | Output |
|---|---------|---------|----------------------|--------|
| 1 | Análise CV da imagem | `image_analyzer.py` | Pillow, K-means (sklearn), skimage regionprops | Paleta de cores, regiões com bbox e shape_type, zonas de texto |
| 2 | Detecção de padrões | `pattern_detector.py` | Geometria pura (Python) | Regiões anotadas com `foreach_*` para grids/listras |
| 3 | OCR | `ocr_extractor.py` | EasyOCR + PyTorch (CPU) | Lista de textos com bbox em cm, font_size_pt, cor estimada |
| 4 | Matching de fontes | `font_matcher.py` | Heurística aspect-ratio + prior Swiss Design 70% grotesca | `latex_pkg`, `latex_cmd`, `weight_hint` por texto |
| 5 | Montagem do JSON | `cover_assembler.py` | Orquestra 1–4 | `cover_analysis.json` (schema v1.0) |
| 6 | Enriquecimento VLM | `replicate_cover.py` → Gemini API | Gemini 2.5-flash (opcional, `--semantic`) | JSON com `semantic_role` adicionados por visão |
| 7 | Geração TikZ | `tikz_generator.py` | Python puro, sem LLM | `.tikz` com `\newcommand{\RenderDynamicCover}` |
| 8 | Compilação LaTeX | `lualatex` (MiKTeX) | LuaLaTeX rodado 2×, `\usepackage{fontspec}` | PDF (produto final) |
| 9 | Render PDF → PNG | `pymupdf` (`fitz`) | Render página 0 a 150 DPI | PNG para comparação visual |
| 10 | Comparação de qualidade + Patch Engine | `visual_comparator.py` | SSIM (skimage), K-means paleta, comparação por região | SSIM, color_dist, region_match_rate, diff_map.png |

O Patch Engine roda dentro do loop de `replicate_cover.py`:
aplica `patch_hints` (cores erradas detectadas) → regenera TikZ → recompila → reavalia.
Para quando SSIM não melhora ≥ 0.005 entre passes (early-exit adicionado na sessão atual).

---

## Estrutura de arquivos

```
automation/
  scripts/
    image_analyzer.py        # Etapa 1
    pattern_detector.py      # Etapa 2
    ocr_extractor.py         # Etapa 3
    font_matcher.py          # Etapa 4
    cover_assembler.py       # Etapa 5
    tikz_generator.py        # Etapa 7
    visual_comparator.py     # Etapa 10
    replicate_cover.py       # Orquestrador geral (etapas 6, 8, 9 + loop de patch)
  prompt/
    replicate_prompt.txt     # System prompt para o passo VLM
  output/
    replicated/
      <stem>_analysis.json   # JSON da análise CV + OCR
      <stem>_cover.tikz      # TikZ gerado
      <stem>_cover.tex       # Wrapper LaTeX
      <stem>_cover.pdf       # PDF final
      <stem>_render.png      # PNG para SSIM (não é o produto final)
      <stem>_diff.png        # Diff map: original | heatmap | render
```

---

## Resultado do primeiro teste (capa_teste4.png — pôster David Bowie)

```
Pass 1: SSIM=0.6039  regions=11%
Pass 2: SSIM=0.6539  regions=89%  (patches corrigiram cores)
Pass 3: SSIM=0.6539  regions=89%  → early exit (sem melhora)
Final:  SSIM=0.6539  FAIL (threshold 0.82)
```

**Produto final:** `capa_teste4_cover.pdf` — visualmente ruim.

---

## Diagnóstico dos gargalos

### Gargalo 1 — `image_analyzer.py` → `_extract_regions()` (PRINCIPAL)

O pôster David Bowie Dunstable é um **retrato pixelado** (blocos retangulares coloridos
formando um rosto). O `_extract_regions` usa K-means no thumbnail + máscara por cor +
componentes conectados na imagem original. Problemas:

1. **Tolerância de cor muito larga (±40 RGB):** pixels de bordas de blocos diferentes
   "vazam" uns para os outros, conectando blocos adjacentes numa única componente irregular.
2. **Threshold de retângulo muito alto (fill_ratio > 0.88):** blocos retangulares com
   bordas anti-serrilhadas ou JPEG ficam abaixo de 0.88 e são classificados como `polygon`.
3. **Sem fechamento morfológico:** pequenas falhas na máscara (1–3px) quebram
   componentes que deveriam ser contíguas.
4. **Blocos pequenos filtrados (< 2.5% da área):** para retratos pixelados com 20–30
   blocos, cada bloco cobre ~3–5% — próximo do threshold, alguns são descartados.
5. **Sem detecção de grade:** o sistema não tenta encontrar as linhas horizontais/
   verticais que definem os blocos da grade Mondrian.

### Gargalo 2 — `tikz_generator.py` (secundário)

Formas `polygon` → fallback para retângulo (bbox). Blocos diagonais ou irregulares
perdem geometria.

### Gargalo 3 — Patch Engine não corrige estrutura

O Patch Engine corrige apenas cores de regiões mal-detectadas. Se a detecção de bbox
estiver errada, mais passes de patch não ajudam.

---

## Mudanças por ciclo

### Ciclo 1 — Sessão inicial (implementação dos 10 estágios)

**Pedido:** Construir pipeline Swiss Cover Replicator do zero, 10 estágios.

**Decisões tomadas:**
- EasyOCR em vez de PaddleOCR (paddle não tem wheel para Python 3.14)
- LuaLaTeX direto (2×) em vez de latexmk (não instalado no sistema)
- pymupdf (`fitz`) para render PDF→PNG (sem dependência de sistema)
- Sistema de coordenadas TikZ (y=0 embaixo-esquerda) em toda a pipeline
- Prior bayesiano 70% grotesca no font_matcher (Swiss Design dominance)

**Bug corrigido:** linhas sem `%` após `\begin{document}` criavam parágrafo vazio
→ TikZ na página 2, página 1 branca. Corrigido com `%` no fim das linhas críticas do wrapper.

**Bug corrigido:** early-exit do Patch Engine — sem o check de SSIM estagnado, o loop
rodava os 3 passes mesmo sem melhora. Adicionado: para se `ssim_new <= ssim_prev + 0.005`.

---

### Ciclo 2 — Melhoria do gargalo 1 (image_analyzer + cover_assembler)

**Pedido:** Corrigir `_extract_regions()` para detectar melhor blocos retangulares em
capas estilo Mondrian / retrato pixelado.

**Mudanças aplicadas em `image_analyzer.py`:**

1. **`_detect_grid_blocks()` (nova função):** Detecção de grade via Sobel + perfis de projeção.
   - Calcula gradiente horizontal/vertical com `skimage.filters.sobel_h/v`
   - Perfil de projeção = média da magnitude por linha/coluna → picos = linhas de grade
   - Cada célula da grade vira uma região com cor dominante (mediana do ROI)
   - Ativado automaticamente se ≥ 2 linhas de grade detectadas em qualquer eixo
   - Fallback: método anterior (connected components por cor)

2. **`_MASK_COLOR_TOL` reduzido 40 → 25:** tolerância de cor mais apertada
   evita que pixels de borda "vaze" entre blocos adjacentes.

3. **`_RECT_FILL_RATIO` reduzido 0.88 → 0.68:** threshold de fill_ratio para
   classificar como retângulo — antes blocos com bordas JPEG eram classificados
   como polygon. Agora 68% de cobertura do bbox já é "retângulo".

4. **Fechamento morfológico (`binary_closing`, disk=3):** preenche pequenas falhas
   em máscaras de cor causadas por anti-aliasing antes de calcular componentes conectadas.

5. **4-connectivity em vez de 8:** reduz conexões diagonais entre blocos adjacentes.

6. **`_MIN_REGION_AREA_FRAC` 0.025 → 0.015:** captura blocos menores (antes alguns
   blocos individuais eram filtrados por serem < 2.5%).

7. **`analyze_image()` aceita `canvas_w_cm` / `canvas_h_cm`:** coordenadas bbox_cm
   agora são relativas ao canvas desejado (A4 = 21×29.7cm), não às dimensões físicas
   da imagem via DPI (que dava 12.12×17.07cm → blocos só cobrindo metade do PDF).

**Mudança em `cover_assembler.py`:**
- `_run_cv()` agora recebe e passa `width_cm`, `height_cm` para `analyze_image()`.
  Fix de bug: antes, as regiões usavam coordenadas de 12.12cm mas o TikZ desenhava
  em 21cm → metade direita do PDF ficava em branco.

**Resultados:**

| Métrica | Antes (ciclo 1) | Depois (ciclo 2) |
|---------|-----------------|------------------|
| Regiões detectadas | 9 | 17 |
| Shape das regiões | polygon/triangle/circle | **100% rectangle** |
| SSIM pass 1 (sem patches) | 0.6039 | **0.7720** |
| SSIM final (após patches) | 0.6539 | **0.7946** |
| Region match final | 89% | 82% |

SSIM subiu de 0.6539 → 0.7946 (+0.14). Ainda abaixo de 0.82.
Próximo gargalo: algumas regiões do grid com cores próximas sendo confundidas pelo patch engine.

---

## Como rodar

```bash
# Teste básico (modo local, sem VLM)
python automation/scripts/replicate_cover.py capas_teste/capa_teste4.png

# Com VLM (requer GEMINI_API_KEY no ambiente)
python automation/scripts/replicate_cover.py capas_teste/capa_teste4.png --semantic

# Analisar imagem isoladamente
python automation/scripts/image_analyzer.py capas_teste/capa_teste4.png
python automation/scripts/image_analyzer.py capas_teste/capa_teste4.png --json
```
