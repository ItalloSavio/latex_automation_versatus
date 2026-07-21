# Swiss Cover Replicator — escopo do sistema

## Objetivo único (North Star)

**Entrada:** uma imagem de capa (estilo Swiss design).
**Saída:** um PDF LaTeX/TikZ **visualmente idêntico** à imagem.
**Autonomia:** o sistema deve iterar sozinho — medir, corrigir, re-renderizar — até
que a comparação máquina-a-máquina considere original e render idênticos.

Nada além disso é escopo. Ver "Fora de escopo" no final.

## Pipeline

```
imagem
  → image_analyzer.py    CV: paleta k-means, grade (Sobel + snap de cor), diagonais
  → pattern_detector.py  repetição/simetria → \foreach   (células grid são puladas)
  → ocr_extractor.py     EasyOCR + medição de TINTA: bbox, baseline, tamanho, peso, cor
  → font_matcher.py      família/peso (peso vem do stroke_ratio medido)
  → cover_assembler.py   junta tudo → cover_analysis.json  (fonte da verdade)
  → tikz_generator.py    JSON → TikZ determinístico (sem LLM)
  → replicate_cover.py   LuaLaTeX ×2 → PDF → PNG (pymupdf) → compara → LOOP de correção
  → visual_comparator.py métricas + diff map + patch_hints
  → calibrator.py        mede a tinta do render vs original → correção por elemento
```

## Loop de auto-correção (replicate_cover.py)

Cada passe: gera TikZ → compila → renderiza → compara (SSIM). Se não bateu a meta,
propõe correções para o próximo passe:
- **calibrator** — mede a tinta de CADA texto no render E no original (mesmo método,
  o viés cancela) e resolve `hscale`/`dx_cm`/`dy_cm` por elemento, com damping 0.8.
  Remove o número mágico: partindo de hscale=1.0 o loop reencontra ~0.89 sozinho.
- **patch** — recolore regiões que o comparator marcou como erradas.

**Hill-climbing:** um passe só é aceito se o SSIM subiu; plateau → para no melhor;
regressão → reverte para o melhor. O output nunca piora. Para quando bate a meta,
não há mais correção, ou esgota `--max-passes`.

Comando: `python automation/scripts/replicate_cover.py capas_teste/capa_teste4.png --max-passes 1`

## Métricas (autoridade: `visual_comparator.py`)

| Métrica | O que é | Meta |
|---|---|---|
| `ssim_global` | SSIM skimage, `channel_axis=2, data_range=255` | ≥ 0.95 |
| `color_dist_mean` | distância RGB média entre paletas k-means | < 5 |
| `region_match_rate` | % regiões com cor certa (≤ 40 RGB) | 100% |

Diagnóstico (ad-hoc, não está no comparator): **SSIM por zona** — gráfica (acima de
y=8.63cm) vs texto. Serve para saber *onde* está o erro.

**Teto realista:** ~0.95. Acima disso é ruído de sub-pixel (vetor rasterizado vs foto)
e recorte exato da fonte. Não gastar esforço perseguindo 1.0.

## Estado atual (capa_teste4 = referência)

`Total 0.9235 | Graphic 0.9555 | Text 0.8497 | regions 100%`

## Constantes calibradas (e por que existem)

Em `tikz_generator.py`:
- `_TEXT_HSCALE = 0.89` — Helvetica do original tem tracking apertado; a fonte de
  render sai ~11% mais larga. **É um número mágico — alvo de auto-calibração.**
- `_TEXT_XSB_EM = 0.043` — side bearing do 1º glifo (nó `base west` ancora na origem
  do glifo, não na tinta).
- `_TEXT_YCORR_EM = 0.091` — só no fallback sem `baseline_y_cm`.
- `_SEAM_BLEED_PT = 0.5` — sangria de mesma cor; fecha a fímbria de anti-alias entre
  polígonos vizinhos. Exige o `\clip` da página (senão estoura pra 2ª página).

Em `ocr_extractor.py`:
- `_MIN_CONFIDENCE = 0.50`, `readtext(width_ths=0.8)` — recupera linhas fracas e
  mantém "A / B" numa string só.
- `_ASCENDER_RATIO 0.735` / `_ASC_DESC_RATIO 0.945` — em a partir da tinta medida.
- `_BOLD_STROKE_RATIO = 0.125` — bold pela espessura de traço medida.

Em `image_analyzer.py`:
- gate de diagonal usa **std do canal MÁXIMO > 15** (a média dos 3 canais mascara
  splits de canal único, ex. magenta vs vermelho).
- linhas de grade sofrem `_snap_line_to_color_edge` (o pico Sobel cai ~1px ao lado).

Fonte: cadeia Helvetica → **TeX Gyre Heros** (clone métrico, letterforms batem) →
Arial. Não há Helvetica real no Windows; Arial tem letterforms diferentes.

## Protocolo de trabalho (SEMPRE seguir)

1. **Medir antes de mexer.** Nunca "achar" a causa — provar com pixels
   (recorte/zoom/scan de cores). Cada bug real hoje foi achado medindo.
2. **Uma mudança por vez → re-medir.** Se não melhorou a métrica, reverter.
3. **Corrigir o algoritmo, não a imagem.** Nada de hack específico de uma capa.
   Se a correção não generaliza, não entra.
4. **Iteração rápida:** reusar `*_analysis.json` cacheado → regerar tikz → compilar →
   SSIM (pula EasyOCR, que leva ~40s). Só rodar o pipeline inteiro para validar CV/OCR.
5. **Regressão:** as 7 capas em `capas_teste/` devem continuar rodando sem quebrar.

## Vocabulário suportado (limite arquitetural)

O sistema é um **reconstrutor estrutural com vocabulário fixo**:
retângulos em grade + triângulos (diagonais) + texto. capa_teste4 encaixa perfeito.
Capas com mosaico/círculos/logo (ex. capa_teste1 ≈ 0.72) estão **fora** do vocabulário
— exigem crescer o vocabulário (dev) ou uma passada VLM, não tuning de parâmetro.

**Um loop otimiza dentro do vocabulário; ele não inventa vocabulário novo.**

## Divisão de trabalho

- **Loop (auto)** — calibração por elemento (escala/posição medidas do render), patch
  de cor, busca entre alternativas de forma. Hill-climbing: aceita só se melhorou.
- **VLM** — só lacunas semânticas: reler texto que o OCR errou, identificar fonte.
- **Dev (humano)** — crescer o vocabulário e corrigir bugs de algoritmo.

## Fora de escopo (NÃO fazer sem pedido explícito)

- Mexer em `styles/`, `brands/`, `vision_extractor.py` ou no template do livro —
  são de outro fluxo, não do replicador.
- Refatorar/renomear módulos que não têm bug.
- Perseguir SSIM > 0.95 com micro-tuning.
- Commitar, dar push ou criar PR sem o usuário pedir.
- Criar arquivos novos (docs, scripts) sem necessidade — preferir editar o existente.
