# automation/tools — diagnóstico e manutenção

Ferramentas de apoio ao replicador. Não fazem parte do pipeline (`automation/scripts/`);
são o que se usa para **investigar** um resultado ou **regenerar** um entregável.

| ferramenta | para quê |
|---|---|
| `diff_blobs.py <n> [top]` | Manchas contíguas onde o render DISCORDA do original, ranqueadas por área, com bbox em cm e as duas cores. É como se acha a causa de "está estranho" sem chutar. A mesma medição roda dentro do pipeline (`visual_comparator.residual_blobs`) para alimentar o VLM. |
| `render_analysis.py <n> [arquivo.json] [tag]` | Renderiza e mede QUALQUER analysis json com a máquina real (tikz → LuaLaTeX → PNG → compare). Serve para comparar duas hipóteses em pé de igualdade. |
| `vectorize.py <n> [eps] [area_min]` | Vetorizador: quantiza na paleta, traça contornos e emite polígonos. **Testado e rejeitado como caminho principal** (ver CLAUDE.md) — fica disponível como rede de segurança local e para experimentos. |
| `merge_capa1.py` | **NECESSÁRIO para regenerar a capa1.** Ela renderiza de um `vlm_analysis.json` cacheado porque o entregável dela é cirurgia manual. Este script pega as REGIÕES frescas do detector e as junta ao TEXTO corrigido do cache. Sem ele a capa1 não é reproduzível. ⚠️ O motivo registrado antes — "o OCR dela é não-determinístico" — foi MEDIDO em 11/09 e é FALSO: `extract_text` rodado duas vezes devolve saída idêntica, até a cor. O que a torna especial é o `"6"` de 411pt que o portão medido MANTÉM porque remover custa 0.13 de Score. |
| `audit.py [n...]` | O `analysis.json` em disco ainda reproduz o `render.png` entregue? Pega a família de bug mais cara do projeto (o pipeline decide uma coisa e o arquivo recebe outra). ⚠️ Ele **não re-roda o OCR** — prova JSON→render, nunca imagem→entregável. Para o ponta a ponta use `cover_pipeline.py --rebuild`. |
| `accept.py [n...] [--json]` | **Esta réplica saiu ENTREGÁVEL?** O veredito que o Score não dá: tipo vazando, blocos sobrepostos, corpo maior que 25% da altura, cor fora da paleta, letras viradas mancha, peças perto do teto. `OK`/`ATENCAO`/`REVISAR`, com código de saída 1 em REVISAR. Roda sozinho no fim de todo `cover_pipeline.py`. |
| `run_batch.py` | Várias capas com progresso visível (escreve `_run_status.md`). ⚠️ Ainda fala das 20 e recusa a capa1 em `plain` — a recusa continua certa (cirurgia manual), o motivo registrado nela não. |

## capa1 — como regenerar

```bash
python automation/tools/merge_capa1.py
python automation/scripts/replicate_cover.py capas_teste/capa_teste1.png --vlm
```

O `merge_capa1.py` parte de `vlm_analysis.json.bak` (o cache com o texto aprovado) e
sobrepõe as regiões que os detectores produzem hoje. **Não** rode `--vlm-refresh` na capa1
sem backup: medido em 11/09, o caminho automático completo dá **0.7304** e um passe fresco de
VLM chega a **0.7349**, contra **0.8132** do manual — e o render automático tem um `"6"` branco
gigante no lugar do anel. O `accept.py` reprova aquele estado com `REVISAR`, o que é a
validação de que o portão discrimina.

⚠️ Um número de **0.8567** circulou para a capa1 automática e era **medição falsa**: saiu de
renderizar um `reader_analysis.json` parado em disco, não de rodar o pipeline.

## Métrica tolerante

`visual_comparator` calcula `content_match_tol` (casamento com tolerância de ±2px) apenas
quando `SWISS_TOL_METRIC=1` está no ambiente — ela custa 0.2–1.0s por comparação e o Score
ainda não a consome. Ligue só para trabalho de calibração de métrica.
