# automation/tools — diagnóstico e manutenção

Ferramentas de apoio ao replicador. Não fazem parte do pipeline (`automation/scripts/`);
são o que se usa para **investigar** um resultado ou **regenerar** um entregável.

| ferramenta | para quê |
|---|---|
| `diff_blobs.py <n> [top]` | Manchas contíguas onde o render DISCORDA do original, ranqueadas por área, com bbox em cm e as duas cores. É como se acha a causa de "está estranho" sem chutar. A mesma medição roda dentro do pipeline (`visual_comparator.residual_blobs`) para alimentar o VLM. |
| `render_analysis.py <n> [arquivo.json] [tag]` | Renderiza e mede QUALQUER analysis json com a máquina real (tikz → LuaLaTeX → PNG → compare). Serve para comparar duas hipóteses em pé de igualdade. |
| `vectorize.py <n> [eps] [area_min]` | Vetorizador: quantiza na paleta, traça contornos e emite polígonos. **Testado e rejeitado como caminho principal** (ver CLAUDE.md) — fica disponível como rede de segurança local e para experimentos. |
| `merge_capa1.py` | **NECESSÁRIO para regenerar a capa1.** Ela renderiza de um `vlm_analysis.json` cacheado porque o OCR dela é não-determinístico (lê o anel como "6"). Este script pega as REGIÕES frescas do detector e as junta ao TEXTO corrigido do cache. Sem ele a capa1 não é reproduzível. |

## capa1 — como regenerar

```bash
python automation/tools/merge_capa1.py
python automation/scripts/replicate_cover.py capas_teste/capa_teste1.png --vlm
```

O `merge_capa1.py` parte de `vlm_analysis.json.bak` (o cache com o texto aprovado) e
sobrepõe as regiões que os detectores produzem hoje. **Não** rode `--vlm-refresh` na capa1
sem backup: o OCR re-erra o título e o resultado automático ainda fica abaixo do manual
(0.685 vs 0.796 medido em 2026-08-06).

## Métrica tolerante

`visual_comparator` calcula `content_match_tol` (casamento com tolerância de ±2px) apenas
quando `SWISS_TOL_METRIC=1` está no ambiente — ela custa 0.2–1.0s por comparação e o Score
ainda não a consome. Ligue só para trabalho de calibração de métrica.
