# doc-pipe — Como funciona o Swiss Cover Replicator

> Documento de estudo. Explica **o que o sistema é**, **como o pipeline está montado**,
> **como ele se corrige sozinho**, **como medimos**, e **onde estão os limites reais**.
> Escrito para quem quer entender o projeto de ponta a ponta, não só rodar.
>
> Última reescrita: 2026-08-06. Substitui a versão de julho, que descrevia o SSIM como
> juiz — isso deixou de valer quando o **Score** entrou.

---

## 1. O que este sistema é (em uma frase)

Você manda **uma imagem** de uma capa em design suíço e o sistema devolve um **PDF vetorial
(LaTeX/TikZ) visualmente idêntico** — e ele **mede o próprio resultado e se corrige** até a
comparação máquina-a-máquina considerar os dois iguais.

Não é "gerar uma capa parecida". É **reconstruir aquela capa específica**, e como
**estrutura** (um círculo é um círculo, um texto é um texto), não como cópia de pixels.

Essa distinção é a decisão de arquitetura mais importante do projeto. Ver §9.

---

## 2. O loop fechado

```
   imagem ──► ANALISA (CV + OCR)  ──►  analysis.json   (a "fonte da verdade")
                                            │
                                            ▼
                                  GERA TikZ determinístico
                                            │
                                            ▼
                                  COMPILA LuaLaTeX → PDF → PNG
                                            │
                                            ▼
                                  COMPARA render × original  →  SCORE
                                            │
                   ┌────────────────────────┴────────────────────────┐
              bateu a meta?                                    não bateu?
                   │                                                 │
                  FIM                              MEDE o erro e propõe correção
                                                   (calibrador · patch · VLM) ──┐
                                                                                │
                                            ◄───────────────────────────────────┘
```

Duas regras governam o loop inteiro:

1. **Hill-climbing.** Um passe só é aceito se o Score subiu. Regressão reverte, platô para.
   **O resultado nunca piora.**
2. **Medir, não confiar.** Nenhum detector é aceito por parecer certo; ele entra se o Score
   medido melhora. Isso já reverteu várias peças que "pareciam certas" (§10).

---

## 3. O pipeline, estágio a estágio

```
imagem
  → ocr_extractor.py     EasyOCR + medição de TINTA: bbox, baseline, tamanho, peso, cor.
                         Roda PRIMEIRO — entrega as caixas de texto ao mapa de layout.
  → image_analyzer.py    CV: paleta k-means, grade (Sobel + snap de cor), diagonais,
                         círculos (Hough), setores de coroa, mosaico, margem de foto.
                         A grade MASCARA as caixas do OCR antes da projeção Sobel, senão
                         letra grande no meio da arte vira linha de grade falsa.
  → pattern_detector.py  repetição/simetria → \foreach
  → font_matcher.py      família/peso (peso vem do stroke_ratio medido)
  → cover_assembler.py   ORQUESTRA a ordem (OCR→CV) e junta tudo → analysis.json
  → tikz_generator.py    JSON → TikZ determinístico (sem LLM)
  → replicate_cover.py   LuaLaTeX ×2 → PDF → PNG → compara → LOOP de correção
  → visual_comparator.py métricas + mapa de diff + manchas de resíduo
  → calibrator.py        mede a tinta do render vs original → correção por elemento
```

### Seleção de camadas (confiança MEDIDA)

Cada detector propõe uma **camada**. Em vez de confiar nele, o sistema **mede**: derruba a
camada e só mantém a queda se o Score melhorar sem ela. É assim que uma capa sem grade real
(capa7) se livra da grade que o detector impôs.

---

## 4. O juiz — como medimos

Autoridade: `visual_comparator.py`.

| métrica | o que é | meta |
|---|---|---|
| **`score`** | **`0.30·SSIM + 0.50·content_match + 0.20·content_iou` — o que o loop otimiza** | ≥ 0.95 |
| `ssim_global` | SSIM skimage | ≥ 0.95 |
| `content_match` | qualidade SÓ nos pixels de conteúdo (não-fundo) | → 1.0 |
| `content_iou` | sobreposição das máscaras de conteúdo | → 1.0 |
| `text_match` | F1 da tinta nas caixas de OCR, **tolerante a desalinhamento** — o portão de TEXTO | → 1.0 |
| `content_match_tol` | `content_match` com tolerância de ±2px. **OPT-IN** (`SWISS_TOL_METRIC=1`) | diagnóstico |

### ⚠️ SSIM sozinho engana

SSIM é ponderado por ÁREA. Uma capa com fundo grande ganha SSIM alto só acertando o fundo.
capa2 tem SSIM 0.94 e `content_match` 0.03. **Sempre olhe os dois juntos.**

### ⚠️ O ponto cego que NÃO conseguimos fechar

`content_match` é **pontual**: compara pixel com pixel, sem tolerância espacial. Como
comparamos arte vetorial rasterizada contra foto/scan, toda borda diverge no sub-pixel.
Traço fino e **curva** são só borda, então são punidos.

Consequência medida: na capa3, uma **grade de barras estruturalmente errada** pontuou 0.747
enquanto o `circle_lattice` **fiel** pontuou 0.611. A métrica premiou o errado.

Tentamos três correções e **nenhuma resolveu**:
- tolerância espacial ±1..3px → continua preferindo a aproximação poligonal;
- comparação multi-escala → piora (capa3 cai);
- F1 de posição de borda → também prefere o polígono.

**Regra prática:** onde há curva ou tipo fino, o **olho** é o desempate; o número não é.
Não gaste outra rodada tentando consertar isso com mais uma métrica de pixel.

---

## 5. O vocabulário (o que o sistema sabe desenhar)

Tudo é **dado** no `analysis.json`; o renderizador é determinístico.

| primitivo | onde nasceu | observação |
|---|---|---|
| retângulo / grade | capa4 | a base |
| triângulo (diagonal de célula) | capa4 | par de meias-células |
| círculo / anéis radiais | capa1, capa7 | Hough + bandas de cor |
| **`annulus_sector`** | capa1 | cunha de coroa. `r_in=0` degenera em fatia de pizza — **o mesmo comando desenha disco, quarto, meio e coroa** |
| **`circle_lattice`** | capa3 | op-art: círculos em checkerboard + lentes vesica |
| **mosaico** | capa1 | malha periódica de células sólidas/diagonais/disco |
| **`hatch`** | capa5 | campo de linhas paralelas (só o VLM emite) |
| **polígono** | Fase 5 | vértices arbitrários — expressa quase qualquer forma como DADO |
| **margem de foto** | capa5 | moldura de papel de um pôster fotografado |
| texto | todas | fonte, peso, entrelinha e posição medidos da tinta |

Cada um entrou com **portão medido** e as outras seis capas como regressão.

### A regra que custou uma regressão para aprender

**Peça nova entra AO LADO do caminho velho, nunca no lugar dele — um portão decide qual
roda.** Quando reescrevi o banding de círculo para todos, a capa7 perdeu dois anéis sutis e
caiu 0.8643→0.8472. Remendar não recuperou; separar os caminhos recuperou exatamente.

---

## 6. O VLM como proponente (Fase 5)

**Princípio:** o VLM **não é protagonista**. Ele é mais um proponente plugado no
hill-climbing que já existia — ao lado do calibrador e do patch.

**Invariante:** o VLM emite **DADO (parâmetros e strings), NUNCA CÓDIGO.** O
`analysis.json` cresce sozinho; o vocabulário-código só cresce com o dev, no portão de
regressão. Sem isso, alucinação viraria código.

### Edits tipados

```
text.string · text.add · text.remove · text.size · text.move · text.hscale
region.color · region.move · region.resize · region.remove · region.add
logo.mark · vocab.gap
```

### O gatekeeper (`edit_gate.py`) — duas camadas

1. **Aterramento** (barato, sem render): cor ∈ paleta? posição ∈ canvas? string cabe?
   primitivo ∈ vocabulário? texto já existe aí? → descarta o obviamente alucinado.
2. **Medido** (um edit por vez, hill-climbing): aplica → renderiza → mede com a **métrica
   certa** → mantém só se melhorou, senão reverte.

### O roteamento de métrica é onde mora a sutileza

Um edit rejeitado com a **métrica inalterada** quase nunca significa "proposta ruim" —
significa que a métrica roteada não consegue vê-lo. Isso aconteceu **três vezes**:

- `text.add` — a média global do `text_match` dilui ao acrescentar caixa. Solução: julgar
  pela **caixa adicionada**, no F1 dela mesma.
- `text.remove` — apagar muda o próprio conjunto de caixas. Solução: julgar pelo **Score**,
  sem guard de `text_match` (a caixa falsa infla a média).
- `text.size` — mesma diluição. Solução: julgar pela **caixa que se moveu**.

**Regra de diagnóstico:** "sempre rejeitado com métrica inalterada" ⇒ suspeite do
**roteamento** antes de suspeitar da proposta.

### Snaps: a proposta dá a GEOMETRIA, os pixels dão o VALOR

- **`snap_text_adds`** — encaixa o bloco de texto na TINTA real: bandas de linha medidas
  (entrelinha verdadeira), fonte pela altura da banda com razão ciente-de-descendente.
- **`snap_region_colors`** — repinta o polígono proposto com a cor **medida** dentro dele.
  Foi isso que fez o 4º setor da capa5 entrar: a forma estava certa, a cor é que reprovava.

---

## 7. Auto-correção guiada por RESÍDUO (a peça de autonomia)

Durante muito tempo o gargalo não foi vocabulário — era **o sistema não perceber o próprio
erro**. Um humano lia o mapa de diff, decidia o que cada mancha era, e escrevia um detector.

Hoje isso é automático:

```
render ──► residual_blobs(): manchas contíguas de discordância, ranqueadas por área,
           cada uma com bbox_cm e as DUAS cores (ORIGINAL=#4CB5B3 vs NOSSO=#1F1F1E)
              │
              ▼
        prompt do VLM: "para CADA uma, diga o que há aí no ORIGINAL e proponha o edit"
              │
              ▼
        gatekeeper (aterra + mede) ──► renderiza ──► resíduo de novo   (até 3 rodadas)
```

Um mapa de zonas diz *"este sexto da página está ruim"*. Uma mancha diz *"nesta caixa o
original é X e você desenhou Y"*. É a diferença entre o VLM adivinhar e ser apontado.

**Parada:** acaba quando nenhuma mancha passa do limiar, quando uma rodada não landa nada,
ou em 3 rodadas. A capa7 devolve **zero manchas** — ela diz sozinha que está pronta.

### Três guardas, todas descobertas por REGRESSÃO

1. **Dedup de `text.add`.** Texto nunca casa pixel-a-pixel, então o resíduo segue marcando a
   área e o VLM re-propõe o bloco que ele mesmo colocou. Sem isso a capa5 empilhou tipo
   sobre tipo (0.7605 → 0.7398).
2. **O resíduo GUIA, nunca BARRA.** "Zero manchas" na rodada 1 pulava o passe inteiro numa
   capa dominada por texto (capa2: 0.3457 → 0.3352) — o detector de mancha é cego a tipo
   fino por construção.
3. **A rede entre rodadas não pode ser hill-climb do Score cru.** O Score é cego a tipo, e
   texto certo sempre custa ~0.005; a primeira versão jogou fora os três blocos aprovados da
   capa6. Discriminador correto: **`text_match`** — adicionar texto sobe, **duplicar** desce.

---

## 8. Estado atual das 7 capas

| capa | Score | roda sozinha? | o que ainda falta |
|---|---|---|---|
| capa4 | **0.9556** | ✅ | referência (grade + diagonais + texto) |
| capa6 | **0.9217** | ✅ | texto miúdo |
| capa7 | **0.8643** | ✅ | revisada e sólida; círculos ±1.5px do original |
| capa1 | **0.7961** | ⚠️ cache | mosaico ok; arco vermelho e marca (fora de escopo) |
| capa5 | **0.7543** | ✅ | hachura (teto de contraste), texto em 300px |
| capa3 | **0.6111** | ✅ | métrica pune a curva; o olho aprova |
| capa2 | **0.3457** | ✅ | Score cego (98% fundo); `text_match` ~0.78 é o gauge honesto |

**capa1 é a única que não fecha ponta a ponta.** O EasyOCR lê o anel dela como o dígito
**"6" a 411pt** e re-erra o título a cada rodada. O entregável dela vem de um
`vlm_analysis.json` cacheado com o texto corrigido; `automation/tools/merge_capa1.py`
regenera as regiões a partir dos detectores atuais. Rodando 100% automática ela chega a
**0.685** — o loop já apaga o "6" e mais quatro elementos espúrios sozinho, mas o tamanho do
tipo ainda sai errado.

---

## 9. Por que estrutura e não vetorização

Testamos um **vetorizador geral** (quantiza na paleta → `cv2.findContours` → polígonos).
Pela métrica ele **ganha em 5 das 7**. Mesmo assim foi **rejeitado como caminho principal**,
e o motivo é o objetivo, não a estética:

- É **transcrição de uma passada**. Não se auto-corrige, porque já é cópia.
- **Não conserta o próprio texto** — traça letra como mancha.
- **Não melhora com iteração.** A qualidade é fixa na qualidade da transcrição.
- A saída não é editável em termos úteis: 56 polígonos versus "mosaico de período 57".
- Degrada onde a fonte é arte vetorial limpa — que é a maioria do design suíço. Veredito do
  usuário na capa3: *"detector = full HD, vetor = 144p"*.

**Papel certo dele:** rede de segurança **local**. Quando o VLM não souber nomear a forma de
uma mancha do resíduo, traçar o contorno **daquela mancha**. Assim a lacuna de vocabulário
deixa de bloquear. A ferramenta está em `automation/tools/vectorize.py`.

---

## 10. O que já foi tentado e REVERTIDO

Guardado porque é caro re-descobrir. Detalhe completo no `CLAUDE.md`.

| tentativa | resultado medido |
|---|---|
| mosaico fino determinístico (1ª vez) | regrediu — alta-frequência pune sub-pixel |
| blend (média chapada em campo de alta-freq.) | regrediu em ambos os alvos — o teto é **contraste**, não frequência |
| setores angulares "versão mínima" | Score não mexeu — o alvo era 9% do foreground |
| grade adaptativa para o mosaico | células caíam sob `min_cell_area` e evaporavam |
| corte vertical na altura toda | regrediu capa5 — o corte vertical é load-bearing |
| filtro de "suporte de linha" | removia linhas de grade parciais legítimas |
| reconciliação texto×círculo "o maior vence" | semanticamente certa, mas regrediu |
| banda de linha em bloco de UMA linha | capa2 caiu 0.607→0.389 — sem mediana, a razão de descendente erra |
| limiar de meia-altura / trim de franja | pioraram; o trim corta ascendente real |
| vetorizador como caminho principal | ver §9 |

**Padrão:** "parece certo no overlay" ≠ "melhora a métrica". E várias dessas só foram
entendidas **depois** da reversão — a reversão apontou o bug real.

---

## 11. Como rodar

```bash
# uma capa, determinística
python automation/scripts/replicate_cover.py capas_teste/capa_teste4.png

# com o proponente VLM (usa o cache de edits; não gasta API)
python automation/scripts/replicate_cover.py capas_teste/capa_teste5.png --vlm

# forçar nova chamada ao Gemini (gasta API)
python automation/scripts/replicate_cover.py capas_teste/capa_teste5.png --vlm --vlm-refresh

# painel visual das 7 (o olho como portão) — rápido, sem re-rodar
python automation/scripts/review_board.py

# onde está o erro, por zona
python automation/scripts/zone_board.py 1 6x4

# manchas de discordância ranqueadas (diagnóstico)
python automation/tools/diff_blobs.py 1 6
```

**Provedor do VLM:** Gemini (`GEMINI_API_KEY`), reusando a infraestrutura do
`vision_extractor` sem modificá-lo.

**Regenerar a capa1:** ver `automation/tools/README.md`. **Não** rode `--vlm-refresh` nela
sem backup.

---

## 12. Limites reais e fora de escopo

**Tetos que não se resolvem com mais engenharia:**
- A fonte é um **clone métrico** de Helvetica (TeX Gyre Heros), não o corte original.
- **Sub-pixel:** vetor rasterizado contra foto/scan trava o SSIM em ~0.95 mesmo quando o
  resultado é idêntico ao olho.
- **Alta frequência com alto contraste** (hachura fina, mosaico denso) — medido duas vezes.
- **Texto abaixo de ~6px de glifo** (capa5 tem 300px de largura): não há o que medir.

**Fora de escopo por decisão:**
- **Reconstruir logomarcas.** O sistema **reconhece** e mostra `"<Nome> (Logo)"` como
  placeholder, registrando a bbox para um passo futuro de inserir a imagem real.
- Mexer em `styles/`, `brands/`, `vision_extractor.py` ou no template do livro — outro fluxo.
- Perseguir SSIM > 0.95 com micro-tuning.

---

## 13. O que vem a seguir

1. **Mais capas.** 13 novas em `capas_teste/novas_capas/`. Servem para descobrir se os
   portões dos detectores são **principiados ou apenas ajustados** a uma capa — que é o
   risco real de ter validado tudo em sete.
2. **Determinismo da capa1** — o último furo no "manda a imagem → sai o PDF".
3. **Vetorizador como fallback local**, ligado à fila `vocab.gap`.
4. **`font.identify`** — o VLM classifica família/peso e o gate testa. Depende de ter o
   arquivo da fonte instalado; senão vira um `font.gap` para o dev.
