# Swiss Cover Replicator — escopo do sistema

## Objetivo único (North Star)

**Entrada:** uma imagem de capa (estilo Swiss design — GENÉRICO: qualquer pôster
Swiss, não só as da Versatus. As **20** capas de teste valem igual — eram 7 até
2026-08-16, quando o usuário somou `capa_teste8..20`; **a capa8 ainda não rodou**.)
**Saída:** um PDF LaTeX/TikZ **visualmente idêntico** à imagem.
**Autonomia:** o sistema deve iterar sozinho — medir, corrigir, re-renderizar — até
que a comparação máquina-a-máquina considere original e render idênticos.
Logo: **identificar** se há logo (sim/não), **não** adicionar/reconstruir.

Nada além disso é escopo. Ver "Fora de escopo" no final.

## ✅ TO-DO — fila de defeitos (ATUALIZAR A CADA MUDANÇA)

Fonte: narração do usuário sobre as 20 capas (2026-08-19). Estados: **ABERTO** ·
**FECHADO** (com a medição) · **BLOQUEADO por X** · **NÃO É CLASSE** (medido: é local, não geral).
Regra: fechar item ABERTO de causa conhecida e correção barata ANTES de atacar BLOQUEADO.

| # | defeito | capas | estado |
|---|---|---|---|
| A1 | texto dentro de círculo era descartado | 11 | ✅ FECHADO — regra cega removida; 3 textos de volta, 0.9438→**0.9463** |
| A3 | costura branca entre formas ("círculo picotado") | 8, 11, 12 | ✅ FECHADO — `_SEAM_BLEED_PT` 0.5→1.0; **+0.044** em 10 capas |
| A5 | texto "comendo" elementos | 17 | ✅ FECHADO — `dedup_text` exige as MESMAS palavras; `'STYLE'` de volta |
| D2 | régua fina descartada | todas | ✅ FECHADO — `min(m.shape)<4` → por ÁREA; capa18 **+0.075** |
| D1 | "UUU": OCR lê gráfico como texto | 10, 1 | 🚫 BLOQUEADO pelo JUIZ — `_select_text` testa e decide MANTER (remover baixa o Score) |
| A9 | textos pequenos não localizados | 9 | 🚫 BLOQUEADO por RECALL do EasyOCR — só 3 leituras na imagem inteira; saída é o VLM |
| A2 | `circle_lattice` perde para o leitor (0.611×0.799) | 3 | ⏸️ DECIDIDO: **portão soberano**. Caso-teste de qualquer juiz futuro |
| A4 | "the shining" some no preto | 19, 17, 2 | 📋 ABERTO — é **cor por trecho**. Medido: 16 blocos em 8 capas têm texto a <60 RGB da região sob eles. Guard local pelo CENTRO foi TENTADO e REVERTIDO (capa2 +0.070, capa17 **−0.073**): amostrar um ponto não descreve texto que atravessa regiões |
| A6 | peças iguais com cores diferentes | 18, 10 | ✅ FECHADO — o **patch engine** media a cor média DENTRO do bbox da peça; num triângulo esse bbox cobre metade do vizinho, então a cor "medida" é uma mistura inexistente no design. A capa18 acumulou **38 cores de uso único** (46 entradas para um pôster de 3 cores). Patches agora ENCAIXAM na paleta medida (válvula: cor a >90 RGB de tudo passa — é cor real que a paleta perdeu). Peças com cor inventada: capa18 40→**0**, capa10 3→**0**; Score inalterado (as cores valiam 0.0001) |
| A7 | círculo (ex-"6") torto | 1 | 📋 ABERTO |
| A10 | "falta desenhar o resto" | 20 | ✅ FECHADO — era o piso de área; capa20 0.8898→**0.9003** |
| T6 | distância entre cores NÃO diz se elas devem fundir | 10 | 📋 ABERTO — eu havia fechado isso como "NÃO É CLASSE" porque o par da capa10 (69.6) é dos mais separados. **Errado**: aqueles dois laranjas partem UMA barra em duas. O critério certo não é distância, é se fundir **junta componentes numa forma melhor** |
| T5 | capa17 voltou 0.8643→0.8076 após a reversão do guard | 17 | 📋 ABERTO — o código está igual ao original; ela roda `--vlm` e o gate re-julga os edits cacheados contra a análise nova. Verificar se é re-decisão legítima ou perda |
| A11 | alinhamento e escrita ruins | 14, 15 | 📋 ABERTO — teto conhecido: glifos se tocam, banda não mede |
| D4 | "anel" vira tiras laterais | 10 | 🚫 BLOQUEADO — **NÃO É um anel**. Medido: o núcleo vermelho corre 690 dos 700px de altura, então o laranja é um **U aberto**, não uma cavidade — por isso preencher oclusão nunca funcionou lá (não há buraco). O que separava as tiras era o filme `#E79743` (264 componentes de 3–4px); com `drop_films` elas juntam (2.45→**4.99cm**) e o Score sobe de 0.8086 para 0.8100, mas seguem polígonos traçados. **Direção certa:** regra COMPOSICIONAL — quando o bbox da peça A contém B inteira e A é mal explicada, testar A∪B como um primitivo com B pintada por cima (barra arredondada laranja + barra vermelha em cima). Mecanismo novo, não existe hoje |
| T1 | **descartes sem medição** no pipeline | todas | 🔄 EM CURSO — **2 de 19 fechados**. (a) piso de ÁREA do leitor 0.0006→**0.00015**: capa18 perdia 10.56% da página e capa20 6.02% logo abaixo da linha; varrido pelo renderizador real, capa18 0.7876→**0.8076**, capa20 0.8898→**0.9003**, controles imóveis. ⚠️ capa3 NÃO melhora — baixar o piso 4× não recupera 1 peça lá, os 9.76% dela são filme de 1px pego por `min(shape)<2`, ou seja formas que NÃO SE ENCOSTAM, não formas ausentes. (b) piso de confiança do OCR: o piso de confiança do OCR. Medido nas 8 capas com problema de texto: entre 0.20 e 0.45 tudo que é real tem 9–34 caracteres e o lixo tem 1–3 (`'9'`, `'222'`, `'8'`); abaixo de 0.20 o lixo volta a ser longo (capa14, tipo rotacionado, 20–30 chars a 0.00–0.04). Regra nova: `conf≥0.20 E ≥8 alfanum`. capa18 3→**5** textos (+0.003), capa2 →**13** textos; capa4/13/20/6 idênticas. Restam: `h_box_cm<0.15`, guards de círculo do `image_analyzer` |
| T2 | `_select_text` sem guard | — | 📋 ABERTO — apagar é destrutivo, deveria exigir evidência forte |
| T3 | capa1 depende de cache manual | 1 | 📋 ABERTO — automático dá 0.7346 × 0.8154 manual |
| T4 | 11 capas nunca viram o VLM | 3,4,8,9,11,12,13,16,18,20 | 📋 ABERTO — custa API, priorizar por capa |

## Direção estratégica (o reframe — LER ISTO)

O gargalo NÃO é mais gerar TikZ nem falta de vocabulário. É **entender a ESTRUTURA
visual** — o sistema deixou de ser "conversor PNG→TikZ" e virou um **compilador de
linguagem visual**. Ele responde bem "o que existe na imagem?" mas mal "como os
elementos se relacionam?".

**Mentalidade FEATURE, não detector.** Em vez de um detector por forma (que vira um
amontoado de IFs), extrair **features que compõem**: periodicidade, simetria,
orientação, densidade, ritmo, grid. UMA feature (periodicidade) explica op-art de
círculos + hachura + mosaico. Feature é contínua → carrega **confidence** de graça.

**Confidence** = triagem barata + **gatilho do VLM** (confiança baixa em tudo =
ambiguidade = chama VLM). NÃO é o portão principal — o portão é a **contribuição
MEDIDA** (render com/sem → mantém só se o Score sobe; auto-confiança pode estar
confiantemente errada, ver as reversões).

**Ressalva dura:** feature/pattern melhora REPRESENTAÇÃO, não fidelidade de RENDER.
Reconhecer o padrão ≠ renderizar bem (mosaico de alta-freq. regrediu mesmo detectado
certo). Toda feature entra só com o portão do Score.

**Roadmap (ordem importa):**
```
FASE 1  ✅ FEITO — Função objetivo (Score) + loop otimiza por ELE, não só SSIM
FASE 2  ✅ FEITO — Layering medido (_select_layers): só fica a camada se o Score piora
        sem ela. Anti-revert. "Confidence MEDIDA" — o detector erra, o render não mente.
FASE 3  ✅ EXPLORADA — Features/padrões: hachura (bloco sólido) e corte-h ciente-de-texto
        ENTRARAM; mosaico fino + op-art de círculos são TETO MEDIDO (alta-freq regride,
        ver Reversões). Setores angulares construídos mas revertidos (não eram o gargalo).
FASE 4  ✅ EM USO — Mapa de layout (texto→grade, pad da caixa) + `zone_board.py`
        (de-average do Score: mede erro×área por zona). Relação texto×círculo tentada,
        revertida (teto de renderização de texto).
FASE 5  ✅ FEITO — VLM como PROPONENTE de edits no loop (NÃO protagonista). Detalhe
        completo em "## VLM — integração (FASE 5)".
FASE 6  ✅ FEITO (branch `new_covers`, 2026-08-16/18) — a REESCRITA DO LEITOR, forçada
        pelas 13 capas novas. Detalhe em "## FASE 6". Em 4 passos aprovados pelo usuário:
        (1) primitivos AUTO-SUFICIENTES, (2) `structural_reader.py` no lugar de um
        detector por forma, (3) VLM tipografia-primeiro, (4) o juiz passa a enxergar texto.
```

**⚠️ A FASE 3 dizia que o teto era "alta-frequência". Estava ERRADO** e a Fase 6 provou:
o mosaico da capa18 e a malha da capa16 são alta-frequência e renderizam bem. O teto era
o `triangle` não conseguir carregar a própria orientação. Ver "## FASE 6".

**Ranking por Score (2026-08-19):** capa4 0.968 | capa6 0.950 | capa12 0.948 | capa11 0.946 |
capa9 0.937 | capa8 0.932 | capa7 0.924 | capa19 0.919 | capa13 0.919 | capa16 0.910 |
capa20 0.880 | capa17 0.865 | capa1 0.817 | capa10 0.807 | capa3 0.799 | capa5 0.774 |
capa18 0.769 | capa14 0.615 | capa15 0.581 | capa2 0.581. **Média 0.842, dez em ≥0.90.**

⚠️ **O NÚMERO NÃO SEPARA AS CLASSES DO OLHO (medido 2026-08-19, LER ANTES DE PRIORIZAR).**
O usuário classificou as 20 em BOAS (1,2,4,6,7,12,13,16), OK (3,8,9,11,15,17,18,19,20) e
PÉSSIMAS (5,10,14). Cruzando com o Score da época: BOAS iam de **0.581 a 0.968**, PÉSSIMAS de
**0.615 a 0.802** — sobreposição quase total. capa2 é BOA com 0.581; capa15 é OK com 0.581
idêntico; capa10 e capa5 (PÉSSIMAS) pontuavam ACIMA de capa3, capa18 e capa2. **Priorizar
pelo Score levaria a trabalhar na capa2, que já está aprovada, e adiar as duas piores.**

**Régua de "pronto":** content ≥ 0.85 E o olho aprova no `review_board.py`.
O olho é reforço/desempate; a métrica é o juiz primário (determinístico).

## FASE 6 — o leitor genérico (a mudança mais importante do projeto)

**O que forçou:** o usuário somou 13 capas. Na 1ª rodada **6 das 12 falharam por PRODUÇÃO**
(o desenho já saía errado, antes de qualquer medição): capa13 é uma grade de quadrados e
colapsou, capa18 é mosaico de triângulos e o `_detect_mosaic` **nem disparou**, capa16 são
losangos e nada pegou. Diagnóstico: **os detectores estavam overfitados nas 7 originais** —
guardas conservadoras calibradas pra não regredir as antigas barravam os casos novos legítimos.

**A prova que fechou o diagnóstico (capa13):** medi a estrutura verdadeira com componentes
conexos (~15 linhas) e mandei pro MESMO renderizador, MESMO vocabulário, MESMO texto do OCR.
**0.490 → 0.890.** O renderizador não era o gargalo; o vocabulário não era o gargalo; **o
leitor era.** A causa exata na capa13: a projeção Sobel achou 5 das 8 bordas verticais
(perdeu as bordas ESQUERDAS dos quadrados 2-4) → cada célula ficava montada sobre um vão → a
cor mediana virava CINZA; e o corte `h_px*0.73` cortava a fileira de baixo. De quebra, os
cinzas inventados eram **acrescentados ao `colors`** com coverage 0.0 — a análise envenenava
a própria paleta.

**Passo 1 — primitivos AUTO-SUFICIENTES (`tikz_generator`).** Um `triangle` agora carrega
`points_cm` (3 vértices) ou `orientation` (ul/ur/bl/lr), e é EXCLUÍDO do pareamento (senão
seria desenhado 2×: sozinho e pelo par). Novos: `ellipse` (o `circle` usava `min(w,h)` e
encolhia bbox oblonga), `rounded_rect` (+`radius_cm`), e `rotation_deg` no texto (o guard de
overflow é pulado pra texto rotacionado — ele mede contra a borda direita, que só limita
texto horizontal). **Aditivo: 25/25 saídas TikZ byte-idênticas.**
⚠️ **Este era o bloqueio real.** O triângulo solto caía num canto CHUTADO: o leitor achava
os 86 triângulos da capa18 CORRETAMENTE e o render dava 0.217, metade espelhados.

**Passo 2 — `structural_reader.py`: UM leitor no lugar de um detector por forma.**
```
quantiza na paleta medida
  → componentes conexos por cor        (isso JÁ É o ladrilhamento, seja qual for a forma)
  → para cada componente, o primitivo que melhor EXPLICA os pixels (IoU): rasteriza
    retângulo/círculo/elipse/rounded_rect/contorno traçado e mede
  → separa (distance transform + watershed) o blob que NENHUM primitivo explica (IoU<0.90),
    e só mantém a separação se as partes explicam melhor
```
Medir vence a assinatura de preenchimento que substituiu: 0.5 podia ser triângulo ou meia-lua,
0.785 podia ser círculo ou quadrado arredondado. **O IoU do vencedor É a confiança.**
Duas coisas que os pixels sozinhos erram, ambas tratadas: **TEXTO** (as caixas do OCR são
mascaradas antes de traçar, senão as letras voltam como poliguinhos DEBAIXO das palavras que a
camada de texto desenha) e **formas que se TOCAM** (os círculos brancos da capa11).
Fiado como `_select_reader` no estágio 7 do `replicate_cover`, **AO LADO** dos detectores:
renderiza os dois e fica com o melhor. **16 de 19 melhoraram; nas outras 3 o portão mantém
os detectores.** Média de Score 0.654 → 0.755.

**Passo 3 — VLM tipografia-primeiro.** Ops novos `text.rotate` e `text.weight` (o prompt
mandava julgar PESO e não existia op pra isso), ambos julgados **pela caixa que mudou** — o
mesmo roteamento que já foi necessário 4×. `region.add` valida a forma contra `_ADD_SHAPES`.
Prompt reenquadrado: o leitor cuida da geometria, então pese TIPO primeiro.

**Passo 4 — o juiz passa a enxergar texto. E aqui eu estava ERRADO, ver "O juiz".**

## Pipeline

```
imagem
  → ocr_extractor.py     EasyOCR + medição de TINTA: bbox, baseline, tamanho, peso, cor
                         (roda PRIMEIRO — dá as caixas de texto ao MAPA DE LAYOUT)
  → structural_reader.py LEITOR GENÉRICO (Fase 6) — componentes conexos → primitivo por IoU.
                         Roda AO LADO do image_analyzer; o portão medido escolhe (estágio 7)
  → image_analyzer.py    CV: paleta k-means, grade (Sobel + snap de cor), diagonais,
                         círculos (Hough). A grade MASCARA as caixas de texto do OCR
                         antes da projeção Sobel → letras não viram linhas de grade.
  → pattern_detector.py  repetição/simetria → \foreach   (células grid são puladas)
  → font_matcher.py      família/peso (peso vem do stroke_ratio medido)
  → cover_assembler.py   ORQUESTRA a ordem (OCR→CV) e junta tudo → cover_analysis.json
  → tikz_generator.py    JSON → TikZ determinístico (sem LLM)
  → replicate_cover.py   LuaLaTeX ×2 → PDF → PNG (pymupdf) → compara → LOOP de correção
  → visual_comparator.py métricas (SSIM + content_match) + diff map + patch_hints
  → calibrator.py        mede a tinta do render vs original → correção por elemento
```

## Mapa de layout (peças determinísticas: texto→grade)

O problema: a detecção de grade (Sobel) roda cega na imagem toda, então **texto
grande no MEIO da arte** (ex. "rancid" na capa6) vira linhas de grade falsas que
estilhaçam a grade em tiras. capa4 escapa disso por sorte de layout (texto embaixo).
**Solução:** OCR roda primeiro; `cover_assembler` passa as caixas de texto pro
`image_analyzer`; `_detect_grid_blocks` zera o gradiente Sobel nessas caixas. Só a
BUSCA-DE-LINHA é mascarada; a classificação de cor/diagonal por célula usa os pixels
reais. **Determinístico** (o OCR *diz* onde é texto — não "acha" por heurística de
borda, que confundia círculo com texto). Ganho: capa6 0.811→0.861 SSIM, content
0.749→0.850. **Peça círculo→grade foi tentada e REVERTIDA** (mascarar círculo da
grade regride — a grade carrega cor que o círculo não substitui).

**Peça 2 (corte horizontal ciente-de-texto):** a busca de linhas horizontais era
capada no topo 73% (cego) pra pular a banda de texto do rodapé. Mas capa SEM texto é
gráfica até embaixo (op-art da capa3) — o corte deixava o terço de baixo como UMA
banda alta, que o passe de diagonal fatiava em triângulos falsos (com as cores-fantasma
de anti-aliasing das bordas curvas). **Fix:** `graphic_rows_h = h_px se NÃO há
text_boxes senão int(h_px*0.73)`. Sem texto → altura toda. Genérico e guardado: as 5
capas com texto ficam idênticas (mesmo 0.73); só capa3/capa5 (0 textos) mudam. Ganho:
capa3 0.602→0.747, capa5 0.586→0.612, zero regressão.

## Loop de auto-correção (replicate_cover.py)

Cada passe: gera TikZ → compila → renderiza → compara (SSIM). Se não bateu a meta,
propõe correções para o próximo passe:
- **calibrator** — mede a tinta de CADA texto no render E no original (mesmo método,
  o viés cancela) e resolve `hscale`/`dx_cm`/`dy_cm` por elemento, com damping 0.8.
  Remove o número mágico: partindo de hscale=1.0 o loop reencontra ~0.89 sozinho.
- **patch** — recolore regiões que o comparator marcou como erradas.

**Hill-climbing:** um passe só é aceito se o **Score** subiu (Fase 1: era só SSIM);
plateau → para no melhor; regressão → reverte para o melhor. O output nunca piora.
Para quando bate a meta, não há mais correção, ou esgota `--max-passes`.

Comando: `python automation/scripts/replicate_cover.py capas_teste/capa_teste4.png --max-passes 1`
Painel visual (o olho como portão): `python automation/scripts/review_board.py --build`

**`snap_text_adds` (edit_gate) — encaixa o text.add do VLM na TINTA real (capa6/7/2):** o VLM
LÊ a string certa mas POSICIONA impreciso → o `box_local` reprovava por posição. O snap isola
o traço do texto de blocos/bordas e encaixa o bbox no extent da tinta, medindo a fonte pela
altura do glifo. **Tinta = RELATIVA** (`g < max_filter-55 & max_filter>100`) — pega preto-no-
laranja E cinza-claro-no-creme (capa2 body do DESCRIÇÃO é cinza ~135, o threshold absoluto
`<80` perdia → snap só achava o header → colapso). **Linhas vazias do VLM = ESPAÇADOR**
(`apply_edit` mantém as vazias interiores; o VLM usa `DESCRIÇÃO /\n\n\nMaterial…` pra gapear
header↔body — dropá-las colapsava os dois um sobre o outro). Guardas: clamp de deslocamento (X apertado — texto alinha
na margem do grid, o VLM acerta X; Y deriva mais), piso de fonte 8pt, `_TEXT_ADD_SCORE_TOL =
_GUARD_EPS` (o box_local é o JUIZ; o Score cego não veta texto bem-posto). Rodado no `_vlm_pass`
ANTES do gate. Provado capa6: os 3 blocos do VLM (box_local 0.25/0.26 → 0.61/0.71/0.54)
ENTRARAM, os 4 textos completos, aprovado pelo olho. Tentar apertar o leading (nlines·font)
REGREDIU um bloco de leading nativo largo → revertido; o extent da tinta É a altura do bloco.

**Refino de texto (2026-08-03) — 4 peças gerais no snap/gate/render:**
- **Tinta DIREÇÃO-CIENTE** — o snap escolhe pela COR do texto: escuro→escuro-no-claro,
  CLARO→claro-no-escuro (`g>minfilter+55 & minfilter<155`). Sem isso o "systems" da capa7
  (branco no preto) sumia (o snap pegava ruído no preto → box_local 0.148).
- **`_TEXT_ADD_SCORE_TOL` 5e-3 → 0.02** — o `box_local` é o JUIZ do text.add; o Score cego cai
  ~0.005 mesmo em bloco BEM-posto (sub-pixel), então o guard de Score é generoso (só pega
  catástrofe). O 5e-3 apertado matava os blocos da capa7 com box_local 0.87.
- **BOLD na 1ª linha** — `apply_edit` marca a 1ª linha não-vazia de cada bloco text.add como
  `weight_hint="bold"` (convenção Swiss: header/1ª-linha bold, resto regular). Só bloco
  multi-linha (data/"01"/linha solta ficam regular).
- **Cap de OVERFLOW (`tikz_generator._build_text_nodes`)** — encolhe a fonte que passaria da
  borda direita do canvas (o título da capa1 vinha 126pt e vazava). Estima largura ~0.52em/
  char; só encolhe texto genuinamente fora da página → zero regressão nas que cabem.

**SNAP POR BANDAS DE LINHA (2026-08-06) — o LEADING medido, não a média do bloco.** O snap
media o extent de tinta do bloco INTEIRO e o `apply_edit` dividia por nº de linhas: na capa6
isso dava entrelinha 1,563cm contra **0,60cm medidos** (2,6× larga) e a fonte do bloco do meio
colapsava no piso de 8pt. Duas causas medidas: (a) a janela (margem 1,6cm) engolia a BORDA da
diagonal preto/laranja — tinta legítima pro filtro — inflando o extent até a janela toda;
(b) fonte pela MEDIANA das componentes conexas, puxada pra baixo por pingos/vírgulas/altura-x.
Peças novas em `edit_gate` (só para bloco MULTI-LINHA; bloco de 1 linha segue o extent — zero
risco pro "grafik"/"01"/data):
- **`_glyph_only`** — descarta componente que ATRAVESSA a janela (`bh>0.35·h` ou `bw>0.90·w`):
  a borda de região é UMA componente que cruza tudo, o glifo nunca. Window-RELATIVO, não
  mediana de componentes (uma borda estilhaça em centenas de specks de anti-alias e derruba
  qualquer mediana pra 1px — foi o que matou o bloco do meio na 1ª tentativa).
- **`_row_runs`** — runs de linha inkada, filtrando os esparsos (resto de borda: 3-9 px/linha,
  1-2 segmentos) e os altos demais. Texto mede 22-57 px/linha e 5-15 segmentos — medido.
- **`_pick_lines`** — escolhe as N runs que melhor casam `top_i = y0 + slot_i·pitch`. Os `slots`
  vêm da lista de linhas do VLM **incluindo as vazias**, então header gapeado do corpo (capa7
  "systems" ⏎⏎ "25 November to") cai no MESMO modelo linear. O resíduo do ajuste (≤0.35·pitch)
  é o teste anti-alucinação: linha real senta na grade de baseline, tinta perdida não.
- **fonte pela banda com razão ciente-de-descendente** (0.735 sem / 0.945 com, mesmo modelo do
  `ocr_extractor`), **mediana do bloco**: no Swiss o header difere em PESO, não em tamanho
  (conferido no original da capa2), e o em por linha é ±1px ruidoso nessas escalas.
- `apply_edit` consome `lines_cm` (caixa por linha medida) em vez da divisão igual.
Medido: capa6 box_local 0.61/0.71/0.54 → **0.805/0.840/0.785**; capa7 parou de SOBREPOR linhas
("Braun Audio" em cima de "Regie 308") e de VAZAR ("42 Charterhouse Square" saía da página),
box_local 0.866/0.752/0.828. Score cego cai pouco (capa6 0.9259→0.9217, capa7 0.8744→0.8643) —
é o caso conhecido de olho > métrica cega em texto fino. Guarda: banda < 3px = ruído → fallback
(protege a capa5, que tem 300px de largura).

**capa5 (2026-08-06) — o snap no PISO DE RESOLUÇÃO: quando não dá pra medir, NÃO CHUTE.**
capa5 tem 300×420px: corpo de texto com **6px** de glifo e o título fundido no grafismo. O
entregável dela era de 31/07 e o rebuild com o snap por bandas SAIU PIOR (grafik 43.6→8pt,
sobrepondo o bloco de baixo) — quatro defeitos gerais vieram à tona:
- **Banda em bloco de 1 linha: TENTADO e REVERTIDO (medido).** Unifiquei os dois caminhos no
  modelo de banda; a capa2 REGREDIU nos 3 blocos de 1 linha (data box_local 0.607→**0.389**,
  rodapé 0.718→0.631). Causa: com uma banda só, o em sai da razão ciente-de-descendente e
  quando a banda CORTA um descendente fino (o 'j' de "12 de junho") a razão é a errada, sem
  mediana pra diluir. **Banda só rende onde há ENTRELINHA (n≥2)**; n=1 fica no extent.
- **Fit vacuoso com N=2.** Reta por 2 pontos tem resíduo ZERO sempre → o teste de regularidade
  não decide nada, e a capa5 PULOU "verbandes schweiz. grafiker" pra parear a linha 1 com a
  1ª linha do bloco SEGUINTE (pitch de exatamente 2 linhas). Fix: custo por `pitch/altura` e,
  o que realmente resolve, **prior de EXTENSÃO** — o VLM erra a posição mas acerta o tamanho
  do bloco, então `|span − bbox_h|` separa o par certo (16px vs bbox 17px) do errado (26px).
  Verificado: no-op em capa2/6/7 (span bate em ≤0.16).
- **`_glyph_only` matava o próprio TÍTULO.** O limite era 0.35×janela; o "grafik" tem letras
  de ~30px numa janela de 75 → descartado, e o snap lia o texto pequeno de baixo COMO o
  título. O limite agora vem da altura do BLOCO (`1.5·span_px`, teto 0.9×janela).
- **Fallback que NÃO CHUTA.** O extent do "grafik" também mente: suas letras ENCOSTAM na borda
  gráfica e viram UM componente de 75px (nada separa isso em 300px), o extent leu 5.25cm e o
  clamp 8–15pt esmagou o título pra 8pt. Sinal medido pra detectar: `_glyph_only` descartou
  **84%** da tinta (num bloco limpo descarta ~0). Então, antes do extent: se sobrou <50% da
  tinta, o snap devolve o edit **INTACTO** — a bbox do próprio VLM é a melhor resposta ali
  (43.6pt). O gate mede de qualquer jeito; não-refinado ≠ errado.
- **Cap de entrelinha no fallback só com n≥2.** Extent inflado espalhava 2 linhas de 6px por
  2.17cm cada → cap em 1.6em. Mas com UMA linha o `line_h` não é entrelinha, é o que assenta a
  linha no fundo da caixa: capar levantou o rodapé direito da capa2 pra cima da régua
  (y 3.60→4.41). Corrigido — cap só quando há 2+ linhas.
Medido no total: grafik box_local 0.650→**0.984**, ausstellung 0.397→**0.731**, kunstgewerbe
0.499, os 3 blocos empilhados com entrelinha certa (o entregável velho não tinha os 2 blocos
pequenos). capa2/6/7 byte-idênticas. **Teto remanescente da capa5: a hachura** (contraste, já
medido e revertido), o texto pequeno saindo maior que o original, e o bloco "kunstgewerbe"
colado no de cima (falta o gap entre blocos — o banding falha nele e o extent não tem o gap).

**CALIBRADOR: NÃO CORRIGIR SOBRE MEDIÇÃO SUJA (achado + fix 2026-08-06).** Rebuild fresco da
capa2 esticava `hscale` até o teto **1.4** em "Versatus HPC Technical Books"/"PROJETO /"/"TIPO /"
→ texto largo e sobreposto (o entregável aprovado não tinha `hscale` nenhum). Provado
pré-existente por CONTROLE: revertendo só o `edit_gate` e re-rodando, os mesmos 1.4 aparecem.
**Causa medida:** a janela do `_measure_ink` é `bbox ± 0.25/0.10cm`; quando a tinta ENCOSTA no
topo/base da janela, ou a caixa está cortada ou a LINHA VIZINHA vazou pra dentro — e aí a
largura medida é a do vizinho, não a do elemento ("e estudo" media want/got = 4.5). Como o
`hscale` é a única alavanca do calibrador, ele "conserta" um erro de ALTURA achatando o tipo de
lado até saturar. Diagnóstico decisivo: **capa4 mede LIMPA em todos os elementos** (h-ratio
1.00–1.09, nada encosta) — por isso a calibração sempre funcionou lá; capa2/6/7 (caixas do VLM,
linhas juntas) estão quase todas sujas. **Fix:** `_measure_ink` devolve `clipped` (tinta toca a
linha do topo ou da base) e `calibrate` PULA o elemento nesse caso. Só o eixo VERTICAL conta —
string longa preenche a caixa de lado por direito. Medido: capa2 perde os 1.4 (sobram 1.065/
1.068/1.010, de medições limpas) e volta a ser RECONSTRUÍVEL do zero; capa4 0.9556 idêntica,
capa3 0.6111 idêntica, capa6 0.9217 e capa7 0.8643 idênticas. capa1/capa5 renderizam direto do
`vlm_analysis.json` cacheado (estágio 13), então o calibrador não as alcança.

**⚠️ TEXTO IGUAL AO ORIGINAL > CONTEÚDO (feedback do usuário, 2026-08-03, LER):** o que importa
é o texto PARECER com o original — TAMANHO, PESO, ALINHAMENTO, LEADING — mais que a string estar
certa. Julgar/consertar comparando a TIPOGRAFIA lado-a-lado com o original, não perseguindo
palavras. (Eu vinha super-indexando em conteúdo; a régua é fidelidade visual do tipo.) Ver a
memória `feedback-visual-fidelity-over-content`. Itens abertos: capa1 título pequeno demais +
vermelho/bold bagunçado + "Material técnico" apagado + data/versão desalinhadas + azul ruim;
~~capa6 leading grande demais~~ ✅ (snap por bandas, 2026-08-06); capa3 ainda "invertida";
capa2 falta a "/" após PROJETO e DESCRIÇÃO.

**⚠️ OLHO > MÉTRICA CEGA (fix de 2026-07-31, LER):** o usuário viu que "depois do VLM
está a mesma coisa". Causa = 4 bugs que ESCONDIAM o VLM do entregável: (1) `review_board
--build` rodava SEM `--vlm` → o board mostrava o determinístico e SOBRESCREVIA o render do
VLM (fix: `_build` passa `--vlm`, reusa cache, sem API); (2) o gate exigia a métrica cega
SUBIR → revertia réguas/strings que o olho quer (fix: `edit_gate._TRUST_OPS =
{"text.string","region.add"}` aceita se ATERRADO e a métrica não REGRIDE além do
`_GUARD_EPS`); (3) a adoção tinha veto de Score global → rejeitava todo o resultado VLM
quando as réguas baixavam o Score cego (fix: estágio 13 do `replicate_cover` reescrito —
CONFIA no gate, renderiza+persiste como ENTREGÁVEL, cacheia o analysis adotado em
`vlm_analysis.json`; no reuse renderiza DIRETO, rápido/reprodutível/sem drift de OCR-id);
(4) re-aplicar edits sobre um analysis já-VLM DUPLICAVA texto (fix: sempre construir do
`best_analysis` determinístico limpo). **Provado na capa2**: réguas+SÉRIE+data+DESCRIÇÃO+01+
HPC entraram, zero duplicata. **Regra dura:** OLHE o `render.png` antes de declarar vitória;
NUNCA reporte a medição interna do gate como se fosse o entregável. content_match é juiz só
onde NÃO é cego (regiões grandes); pra texto/régua fino ele mente.
**Placar por zona (de-average do Score):** `python automation/scripts/zone_board.py 1 6x4`
— corta a capa numa grade, mede `content_match × área` por célula e ranqueia as piores
(erro×área) + metades ESQ/DIR, TOPO/BASE + heatmap. Resolve o ponto cego "o número
global esconde ONDE está o erro" (foi ele que provou: capa1 = mosaico à esquerda 78% do
erro, o alvo só 9% — evita gastar esforço no lever errado). Diagnóstico/roteamento; o
portão de manter/reverter continua sendo o Score global.

## VLM — integração (FASE 5, plano APROVADO pelo usuário)

**Princípio:** o VLM NÃO é protagonista — é só **mais um PROPONENTE de correções**
plugado no hill-climbing que já existe (calibrator e patch já são proponentes; o VLM
entra ao lado). O juiz continua sendo o **portão medido** (Score + regressão). Isso
contém a alucinação: o VLM propõe, o portão dispõe.

**Invariante de determinismo:** o VLM emite **DADO (parâmetros/strings), NUNCA CÓDIGO.**
O mapeamento (`analysis.json`) cresce sozinho; o vocabulário-CÓDIGO só cresce com o dev
no portão de regressão. Sem isso, alucinação viraria código.

**Fluxo (o VLM roda no PLATÔ, não todo passe — controle de custo):**
```
loop determinístico → platô abaixo da meta → VLM DESEMPACADOR:
  ENTRADA aterrada: imagem + render + analysis.json + mapa de ZONAS (zone_board,
                    pior→melhor) + paleta + caixas + métricas + fontes possíveis
  SAÍDA = EDITS TIPADOS (nunca redesenho livre):
     text.string · text.move/scale · region.color · region.move/resize
     region.add(primitivo do vocabulário) · region.remove · vocab.gap
  GATEKEEPER (o intermediário anti-alucinação, 2 camadas):
    ① ATERRAMENTO (barato, SEM render): cor∈paleta? pos∈canvas? string cabe/é real?
       primitivo∈vocabulário? → descarta o obviamente alucinado
    ② MEDIDO (por edit, um a um → hill-climbing): aplica→render→mede com a MÉTRICA
       CERTA (geometria→Score; texto→métrica-texto); mantém só se SUBIU, senão reverte
  → analysis.json atualizado + LOG de auditoria + CACHE (re-run determinístico)
  → vocab.gap vira FILA de vocabulário (dev cresce o primitivo, com regressão)
  GARANTIA: nunca pior que o baseline determinístico.
```

**Métrica de texto (automatizada — o usuário NÃO quer o olho no loop):**
- **Renderização** (posição/tamanho/cor): `content_match` **ponderado pelas caixas de
  texto** + **tolerante a desalinhamento** (dilata a tinta antes de casar → 1px não
  zera). Isto o portão mede e gateia bem. (Resolve o cegueira-a-texto: capa2 = 0.03.)
- **String** (o que está escrito): resíduo IRREDUTÍVEL de confiança no VLM (verificar
  exigiria ler o original — justo o que o OCR não faz). Contido pelo filtro de
  aterramento (implausível → barra) + log pra auditoria HUMANA depois (≠ olho no loop).

**Crescimento do vocabulário (o medo do usuário — resolvido em 2 trilhos):**
1. **Primitivos PARAMÉTRICOS** (polígono geral de N vértices, path, gradiente) — o VLM
   expressa quase tudo escolhendo PARÂMETROS, não código. Renderizador determinístico.
2. **Fila `vocab.gap`** — quando nem o geral expressa, o VLM SINALIZA a lacuna; dev
   cresce o primitivo por DEMANDA MEDIDA (priorizada por quantas capas/quanto erro).

**Ordem de implementação (cada peça medível sozinha, VLM real só no fim):**
```
1. ✅ Métrica-texto (`text_match` em visual_comparator) — validada: capa2 0.03→0.889,
      capa4 0.961, capa1 0.662 (pega o título que vaza: 0.447). Já entra no `compare()`.
2. ✅ Schema de edits + GATEKEEPER (`edit_gate.py`) — 2 camadas + roteamento de métrica.
      Provado com proponente FAKE (SEM VLM): `python automation/scripts/edit_gate.py 7`
      → aterramento rejeita cor fora-da-paleta; medido reverte movção inútil; reparo de
      texto ACEITO (text_match 0.85→0.92); vocab.gap → fila.
3. ✅ Primitivo paramétrico (polígono geral em `tikz_generator._cmd_polygon`) — desenha
      os vértices reais quando a região tem `points_cm`; no-op pras 7 capas (capa4 0.9556).
      O proponente expressa qualquer forma via VÉRTICES (dado), não código.
4. ✅ VLM proponente (`vlm_proposer.py`) — imagem+render+analysis+zonas → **Gemini**
      (visão) → edits tipados → `edit_gate.run_gate`. **Provedor = Gemini** (o projeto já
      tem configurado: `google-genai`, `GEMINI_API_KEY`, cadeia gemini-3-flash→2.0);
      reusa o `_call_gemini`/cadeia do `vision_extractor` SEM modificá-lo. Provado com MOCK
      (`python automation/scripts/vlm_proposer.py 7`), sem gastar API. Ao vivo: `mock=`→`propose()`.
5. ✅ Fila de vocab.gap (`edit_gate.persist_vocab_gaps` → `output/vocab_gaps.jsonl`)
      — o dev cresce o vocabulário por demanda medida.
✅ INTEGRADO no `replicate_cover` (stage 13): flag `--vlm` roda o passe do VLM SÓ no
   PLATÔ, gated pelo `_score_of`; a resposta é CACHEADA em `vlm_edits.json` (re-run
   determinístico; `--vlm-refresh` pra rechamar). Garantia "nunca pior" segura: na
   capa7 (baseline forte 0.8744) o gate reverteu tudo, Score intacto, e a fila pegou os
   gaps (BRAUN logo + blocos de texto). **O VLM ajuda mais onde o determinístico é
   FRACO** (capa2 texto fino, capa1 mosaico), não onde já está forte.
Comando: `python automation/scripts/replicate_cover.py capas_teste/capa_teste2.png --vlm`
✅ CRESCENDO O VOCABULÁRIO por demanda medida (a fila): a maior categoria de gaps era
   TEXTO que o OCR não leu (capa2/5/6/7) → construí o op **`text.add`** (o VLM injeta o
   texto que LEU). Multi-linha: `apply_edit` quebra o bloco em 1 elemento/linha, fonte
   pela altura da linha COM leading (senão sobrepõe). Métrica certa p/ ADIÇÃO: **não** a
   média global do `text_match` (diluída ao somar caixa) nem o Score (cego a texto fino),
   e sim o F1 de tinta da CAIXA ADICIONADA nela mesma (`text_box_scores[-N:]` no compare;
   `_TEXT_ADD_MIN=0.35`). Adoção do `replicate_cover` passou a CONFIAR no gate (adota se
   o Score não cai além do guard `1e-3` — o texto sobrevive ao custo ~0 de Score; o
   guard por-edit do text.add é o mesmo `_TEXT_ADD_SCORE_TOL=1e-3`).
   Provado: capa6, o VLM leu os 3 blocos, o gate aceitou o bem-posicionado (box_local
   0.57) e rejeitou os 2 imprecisos (0.25/0.26 < 0.35). Limite = precisão do bbox do VLM
   p/ texto miúdo. **capa2 (rodada fresca): os 4 vocab.gap de TEXTO da rodada anterior
   viraram 4 `text.add` ACEITOS** (data "12 de junho de 2026" 0.743, "DESCRIÇÃO /" 0.663,
   "01" 0.736, "HPC" vermelho 0.435) + 5 text.string; ZERO vocab.gap novo (o prompt
   melhorado fez o VLM INJETAR em vez de flagar). Score 0.315→0.318 (cego: fundo 98%), mas
   o texto entrou. O "red 'v' logo" segue como gap (LOGO = fora de escopo, não reconstruir).
   Fila restante = primitivos VISUAIS (mosaico/op-art/hachura = teto de CONTRASTE medido).
✅ PRIMITIVO `hatch` (region.add shape=hatch): base opcional + `\foreach` de linhas
   paralelas (`_cmd_hatch`); aterramento valida base_hex∈paleta+bbox; Pass 1 pula, Pass 3
   despacha. **shape_type="hatch" só vem do VLM** — o hatch determinístico da Fase 3 é
   shape_type="rectangle" (source="hatch"), NÃO colide. Medido na capa5 (Gemini ao vivo):
   o hatch de linhas finas (período 0.3cm) REGREDIU 0.6326→0.4979 → **gate reverteu** =
   MESMO TETO do mosaico (alta-freq. pune sub-pixel). Mas a capa5 SUBIU 0.5782→**0.6624**
   assim mesmo: o VLM acertou a decomposição em TRIÂNGULOS (2 polígonos aceitos) + o texto
   "grafik" (text.add box_local **0.984**). Lição repetida: reconhecer o padrão ≠ renderizar
   fino; o primitivo fica disponível p/ hachura GROSSA (onde passa). O fallback de blend
   (média chapada de baixa-freq) FOI construído e REVERTIDO — ver Reversões: o teto restante
   é CONTRASTE, não frequência, então a média apaga a estrutura.
```

**FILA FUTURA (dev) — identificação de FONTE (`font.identify` + `font.gap`):** hoje a
fonte cai sempre no fallback cego (TeX Gyre Heros). Plano APROVADO p/ depois: o VLM (ou um
modelo dedicado de reconhecimento de fonte) CLASSIFICA família/peso/largura do texto e
propõe um `font.identify`; o **gate testa** (fonte casada renderiza mais perto? `text_match`
mede) e mantém se melhor. Ressalva dura: identificar ≠ ter o ARQUIVO — só dá "sem coringa"
se a fonte estiver instalada/licenciada; senão, substituto CASADO (não o default cego) +
um `font.gap` pro dev instalar a real. Mesmo padrão propor→gatear→fila. NÃO implementado.

## ⚠️ O JUIZ — TROCADO E REVERTIDO NO MESMO DIA (2026-08-19). A LIÇÃO É O ATIVO.

**Uma métrica pode ser um bom RANKEADOR e um péssimo ALVO DE OTIMIZAÇÃO.** Concordância de
ordenação NÃO é teste de aceite suficiente. O teste tem que incluir: **rode o loop com ela e
OLHE os renders.**

Troquei `_SCORE_W` para `{ssim: 0.75, structural: 0.25}` porque ele ordenava as 20 capas como
o usuário (71.5% → **82.9%**) e mantinha 4/4 no banco adversarial. Passou nos dois testes que
eu tinha. Rodei as 20 e o usuário reportou **quatro regressões visíveis**: capa2 e capa15
perderam blocos de texto, capa10 perdeu o título de 102pt, capa5 virou "um grande borrão
sólido".

**Mecanismo (medido, não suposto):** nem `ssim` nem `structural` percebem TEXTO FALTANDO — o
ssim mal reage a tipo fino e o structural casa blobs coloridos. Ao tirar `content_match` e
`text_match` do Score, **APAGAR TEXTO virou de graça** e o loop apagou. O `_select_text`
removendo o "UUU" falso da capa10 (que eu comemorei) era o mesmo bug mostrando a metade boa:
ele levou o título junto.

**Revertido para `{ssim: 0.30, content_match: 0.50, content_iou: 0.20}`.** O
`structural_match()` FICA no código, calculado e reportado: é sinal genuinamente bom (76.4%
sozinho) e pertence a um Score futuro que também carregue um termo de PRESENÇA de conteúdo.

⚠️ **Qualquer Score futuro precisa dos dois:** algo que ordene como o olho (ssim/structural)
E algo que puna conteúdo ausente. Só o primeiro degenera; só o segundo é o que tínhamos.

### O que a calibração ensinou e continua valendo
Sobre os 123 pares de classes diferentes (BOAS 1,2,4,6,7,12,13,16 · OK 3,8,9,11,15,17,18,19,20
· PÉSSIMAS 5,10,14): `ssim` 80.5% · `structural` 76.4% · Score atual 71.5% · `content_match`
71.5% · `content_iou` 67.5% · **`text_match` 51.2% (acaso puro)**.
⚠️ **O Score atual NÃO separa as classes do olho** — BOAS iam de 0.581 a 0.968 e PÉSSIMAS de
0.615 a 0.802. Priorizar por ele levaria a trabalhar na capa2 (aprovada) e adiar as piores.
**Use a classificação do usuário para priorizar, não o número.**

## (histórico) O juiz — recalibração de 2026-08-19, revertida acima

O usuário classificou as 20 em **BOAS** (1,2,4,6,7,12,13,16), **OK** (3,8,9,11,15,17,18,19,20)
e **PÉSSIMAS** (5,10,14). Isso virou o alvo: sobre os **123 pares de classes diferentes**,
com que frequência a métrica ordena como ele ordenou? (acaso = 50%)

| sinal | concordância |
|---|---|
| **`ssim` sozinho** | **80.5%** |
| `structural` (casa formas por cor/área/centroide, Hungarian) | 76.4% |
| `score` ANTIGO (0.30/0.50/0.20) | 71.5% |
| `content_match` | 71.5% |
| `content_iou` | 67.5% |
| **`text_match`** | **51.2% — ACASO PURO** |

**`_SCORE_W = {"ssim": 0.75, "structural": 0.25}`** → **82.9%**, e o banco adversarial antigo
seguiu **4/4** (proteção contra sobreajuste: são casos que o usuário julgou antes e que não
entraram na calibração). `content_match`/`content_iou`/`text_match` continuam CALCULADOS e
reportados — viram diagnóstico, param de decidir.

⚠️ **A doutrina "SSIM SOZINHO ENGANA" ENVELHECEU.** Ela era verdadeira quando as capas eram
fundo e faltava conteúdo inteiro — o SSIM premiava acertar o fundo. Depois que o leitor
estrutural passou a acertar a estrutura, deixou de valer, e eu construí em cima dela por
semanas sem re-medir. É o MESMO erro do lattice da capa3 (citei como "prova de juiz quebrado"
falando de um render que não existia mais). **Medição envelhece: re-meça antes de construir.**

⚠️ **`text_match` foi posto no Score em 18/08 e TIRADO em 19/08.** Eu o adicionei argumentando
que "o juiz não via texto". Ele não vê porque **o usuário não julga por isso** — ele mesmo
disse depois: *"sobre o conteúdo do texto, meio que foda-se"*. Construí sobre uma premissa que
nunca verifiquei com ele. O `_content_split` subia as notas sem melhorar a ORDENAÇÃO.

⚠️ **Por que `structural` fica junto do SSIM, e não SSIM puro (80.5%):** ele soma 2.4pp E
herda o papel protetor do `content_match` — o SSIM é ponderado por ÁREA, então uma capa
majoritariamente fundo poderia subir só perfeiçoando o fundo; um render sem formas para casar
tira ~0 no `structural`.

⚠️ **Os pesos exatos NÃO são identificáveis** com 20 capas: só 3 combinações ficam a 2pp do
topo (superfície PICUDA). O que é robusto é a DIREÇÃO — toda combinação com ssim ≥ 0.8 bate o
antigo por 8+ pontos. Não refinar pesos sem mais capas rotuladas.

⚠️ **Custo:** o `structural_match` roda componentes conexos + Hungarian a cada comparação e o
loop compara dezenas de vezes → **3–5× mais lento** (capa14 levou 19min). Aceitável no regime
de uso, mas é de onde vem a lentidão.

**Ainda discorda em:** capa1 (BOA, 0.697) e capa14 (PÉSSIMA, 0.819) são as maiores fontes dos
21 pares invertidos que sobraram.

**GANHO DE GRAÇA:** o `_select_text` (portão medido que remove texto que o OCR inventou)
estava BLOQUEADO — com o juiz velho, remover o "UUU" da capa10 PIORAVA o Score. Com o juiz
novo ele removeu sozinho, no primeiro re-run, **sem uma linha de código nova**.

## O juiz — e a hipótese que NÃO sobreviveu à medição (2026-08-18)

Eu afirmei que o juiz estava quebrado e ia trocar o `content_match` por casamento de formas.
Construí um **banco de provas** (`scratchpad/judge_bench.py`) com os casos em que o usuário
já deu veredicto — vetorizador × detector em capa1/3/5, e capa11 com figura/fundo trocados:

| | `score` | `ssim` | `content_match` | `structural` (a proposta) |
|---|---|---|---|---|
| concordância com o olho | **4/4** | 3/4 | 3/4 | 3/4 |

**O Score atual acerta 4/4. NÃO reescrever o `content_match`.** A evidência que eu vinha
citando — "o lattice fiel da capa3 dá 0.611 e a grade de barras errada dá 0.747" — era sobre
um render que **não existe mais**: o leitor da Fase 6 levou a capa3 a 0.715 e a discordância
evaporou. **Medição velha VENCE; re-medir antes de argumentar.**

**O defeito real, esse sim medido:** `text_match` era calculado, reportado e tinha **peso
ZERO** no Score. Na capa2 ele vale **0.82** enquanto o `content_match` vale 0.157.

**E a correção óbvia NÃO funciona — também medida:** ponderar `text_match` pela ÁREA de texto
falha justo onde é preciso — as caixas da capa2 são **2.0% da página** (capa10 30.5%, capa15
26.3%) e o tipo é o design inteiro dela.

**O que entrou (`_content_split`):** os pixels de CONTEÚDO dentro das caixas de texto vão pro
`text_match` tolerante, o resto fica no casamento estrito, misturados pela fatia de cada parte
**no conteúdo** (nunca na página). Critério de aceite cumprido: o banco de provas **manteve
4/4**. As duas capas SEM texto (capa3, capa11) ficaram **exatamente idênticas** — prova de que
não é leniência global. Média 0.767 → 0.813.
⚠️ **Todo mundo subiu, e isso NÃO quer dizer que as capas melhoraram** — o número passou a
enxergar fidelidade tipográfica, que era invisível. A meta de 0.90 tem que ser lida na escala nova.
⚠️ **Dívida criada:** `_TEXT_ADD_SCORE_TOL = 0.02` existe pela justificativa "o Score cego cai
~0.005 mesmo em texto bem posto". O Score **não é mais cego**, então essa folga ficou frouxa e
deve ser reapertada (é outra medição, não mexer no escuro).

## Métricas (autoridade: `visual_comparator.py`)

| Métrica | O que é | Meta |
|---|---|---|
| **`score`** | **`0.30·SSIM + 0.50·content_effective + 0.20·content_iou` — o que o LOOP otimiza** | ≥ 0.95 |
| **`content_effective`** | **o termo de conteúdo do Score: TIPO medido pelo `text_match` tolerante, o RESTO pelo casamento estrito, misturados pela fatia de cada parte NO CONTEÚDO (`_content_split`)** | → 1.0 |
| `ssim_global` | SSIM skimage, `channel_axis=2, data_range=255` | ≥ 0.95 |
| `content_match` | qualidade SÓ nos pixels de conteúdo (não-fundo) | → 1.0 |
| `content_iou` | sobreposição das máscaras de conteúdo (original vs render) | → 1.0 |
| **`text_match`** | **F1 da tinta nas caixas de OCR, TOLERANTE a desalinhamento (dilata) — o portão de TEXTO do VLM (Fase 5). NÃO é cega a texto fino.** | → 1.0 |
| `color_dist_mean` | distância RGB média entre paletas k-means | < 5 |
| `region_match_rate` | % regiões com cor certa (≤ 40 RGB) | 100% |

`content_match` é duro com texto FINO (capa2=0.03 apesar de visualmente ok) porque 1px
de desvio zera o match ao pixel. **Resolvido pela `text_match`** (Fase 5): mede a tinta
DENTRO das caixas de OCR com dilatação → capa2 sobe de 0.03 pra **0.889** (o texto
renderiza bem, só a métrica global era cega). Validada: capa4 0.961, capa1 0.662 (pega o
título gigante que vaza: 0.447 na caixa dele). É o portão de TEXTO do gatekeeper do VLM.
O `score` global segue com `content_match`; a `text_match` roteia os edits de TEXTO.

**⚠️ SSIM SOZINHO ENGANA — é ponderado por ÁREA.** Uma capa com fundo grande (ex.
capa7 é ~75% preto) ganha SSIM alto só acertando o fundo, mesmo faltando círculos e
texto. Ex. real: capa7 SSIM=0.88 mas content_match=0.32 (reproduz ~20% do conteúdo);
capa2 SSIM=0.94 mas content=0.03 (98% fundo). **Sempre olhar SSIM + content_match
juntos.** capa4 é a única boa nos dois (0.92 / 0.965).

Diagnóstico (ad-hoc): **SSIM por zona** — gráfica (acima de y=8.63cm) vs texto.

**Teto realista do SSIM:** ~0.95. Acima disso é ruído de sub-pixel (vetor rasterizado
vs foto). Mas o SSIM alto NÃO garante fidelidade — cruzar sempre com o content_match.

## Estado atual das 20 capas

⚠️ Score na escala NOVA (pós-`_content_split`, ver "O juiz"). **capa8 nunca rodou.**

| capa | Score | situação |
|---|---|---|
| capa4 | 0.968 | ✅ referência (grade+diagonais+texto). É a única onde os DETECTORES ainda ganham do leitor |
| capa6 | 0.943 | ✅ leitor + 3 blocos de texto do VLM |
| capa12 | 0.935 | ✅ círculos sobrepostos (a transparência sai chapada e mesmo assim casa) |
| capa9 | 0.930 | ✅ array de bolinhas com raio em rampa — o leitor pega sem detector novo |
| capa7 | 0.925 | ✅ (era 0.864 antes da Fase 6) |
| capa13 | 0.916 | ✅ grade 4×4 + círculo. **0.490 antes da Fase 6** |
| capa11 | 0.907 | ✅ lattice de círculos; a INVERSÃO figura/fundo sumiu |
| capa16 | 0.890 | ✅ malha de losangos. **0.406 antes da Fase 6** |
| capa19 | 0.870 | ✅ polígono + tipografia; `text.weight` entrou aqui (box 0.810→0.914) |
| capa17 | 0.840 | ⏳ "1950" ainda sai truncado; Hough alucina anéis sobre a tipografia |
| capa20 | 0.818 | ⏳ quartos de disco fragmentados |
| capa1 | 0.817 | ⏳ anel + mosaico ok. **NUNCA rodar `plain`** (sobrescreve a cirurgia manual: 0.796→0.603) |
| capa10 | 0.792 | ⏳ **é TEXTO, não as barras** — medido 2026-08-18: 22.0% do erro dela está DENTRO das caixas de texto (que cobrem 30% da página) e só 4.4% nas barras. As tiras serrilhadas são reais mas são 1/5 do problema |
| capa5 | 0.777 | ⏳ hachura = teto de contraste (medido 2×) |
| capa3 | 0.715 | ✅ op-art real; sem texto, então o juiz novo não a moveu |
| capa18 | 0.694 | ⏳ mosaico de triângulos REAL (era 0.411); resta um borrão rosa |
| capa14 | 0.595 | ❌ tipografia VERTICAL ausente — o VLM propõe `logo.mark` em vez de `text.rotate` |
| capa15 | 0.581 | ❌ todas as palavras certas, TAMANHOS errados (92% do conteúdo é texto) |
| capa2 | 0.566 | ⏳ texto reconstruído pelo VLM; 38% do conteúdo é texto |

**Falta na capa7 (0.874→0.95):** o falso "alvo" de círculos concêntricos sobre o
texto "BRAUN" (Hough alucina anéis na tipografia), o círculo escuro grande do topo-
esq. (baixo contraste, virou retângulo), e os blocos de texto (só "Walter Knoll" saiu,
lido errado). A grade NÃO era o problema — o `_select_layers` mede que ela ajuda.

## Primitivo `circle_lattice` (op-art de círculos — capa3, ENTROU)

A capa3 é um op-art: círculos navy/azul-claro alternados (checkerboard) + **lentes laranja
horizontais** nas junções. O detector de círculo BAILA em tiling denso → virava grade de
barras (o usuário: "tudo quadrado sendo círculo"). Construído:
- `image_analyzer._detect_circle_lattice` — mede período (autocorr do acento), cores (2
  círculo + 1 lente pelo aspecto largo), raio, tamanho da lente, e a **FASE** (busca a
  máscara-ideal na convenção do renderizador y-up contra o navy do original). Guardas
  CONSERVADORAS (SEM texto + top-3 cores ≥ 82% + acento com ≥5 componentes largos
  periódicos) → **dispara SÓ na capa3** (testado nas 7 com o guard de texto até desligado).
  Se dispara, o lattice SUBSTITUI a grade. As outras 6 = None → render idêntico (zero regressão).
- `tikz_generator._cmd_circle_lattice` — fundo + `\foreach` de círculos (checkerboard) +
  lentes, deslocados pela fase medida. A lente é a **VESICA REAL** (interseção de 2 círculos
  vizinhos via `\clip`), não uma elipse — a elipse gorda fazia o laranja DOMINAR e o usuário
  via "invertido"; a vesica pontuda deixa os círculos dominantes (paridade navy/azul confere
  100%, o "invertido" era a forma da lente, não a cor). **2ª rodada de "invertido" (medida):**
  no original o laranja cobre (i,j+0.5) E (i+0.5,j+0.5) = lentes CONECTADAS em cadeia horizontal;
  a vesica com raio=r caía curta (meia-largura 0.49p < 0.5p) → lentes ISOLADAS, gap azul no
  centro diagonal (orange 0.263 vs 0.304). Fix: clipar de um raio `lr=r+0.02p` (0.72p) → funde
  (orange 0.316, Score 0.598→0.611). O portão é a cobertura de laranja (lr=0.77p deu 0.43, gordo).
- **Eye > métrica (caso puro):** o lattice fiel dá Score 0.599, a grade de barras ERRADA
  dava 0.747 — a métrica cega premia blocos retangulares sobre círculos curvos (98px). Mantido
  pelo OLHO. A fase medida foi crucial: sem ela SSIM 0.118→com ela 0.47 (content 0.25→0.61).

## Primitivo `annulus_sector` (o ANEL da capa1 — ENTROU, 2026-08-06)

O maior objeto da capa1 é um anel Bauhaus: **2 anéis concêntricos × 4 quadrantes**, cada um
com sua cor (externo teal/vermelho/branco/cinza; interno branco/preto/vermelho/teal, com o
preto = fundo). O render fazia dois DISCOS CHAPADOS na metade do raio. Duas causas medidas:
- **`_radial_bands` bandava pela MEDIANA sobre todos os ângulos.** A mediana de 4 cores é uma
  mistura que não casa com banda nenhuma. Peça nova `_angular_bands`: a fronteira radial vem
  da **assinatura por ângulo** (`_CIRCLE_BAND_ANGLE_FRAC`: 25% dos ângulos mudam de vez).
- **⚠️ A peça é ADITIVA, e isso foi APRENDIDO NA REGRESSÃO.** Na 1ª versão eu reescrevi o
  banding para TODO MUNDO — a capa7 perdeu 2 dos seus anéis concêntricos sutis e caiu
  0.8643→**0.8472**. Tentar remendar com "corta se a mediana OU o ângulo mudar" NÃO recuperou.
  O certo: `_angular_bands` devolve **None** quando não há estrutura angular medida (portão:
  ≥50% dos raios precisam ter ≥2 cores não-fundo ocupando ≥25° cada), e aí o círculo cai no
  banding ORIGINAL, verbatim. capa7 voltou a 0.8643 exato. **Regra: peça nova entra ao LADO
  do caminho velho, não no lugar dele — o portão decide qual roda.**
- **O raio do Hough é só um LIMITE INFERIOR.** O quadrante cinza contra o fundo quase-preto quase
  não gera gradiente, então o acumulador picava no disco INTERNO (r=57px) em vez da borda real
  (r=113px). O centro do Hough é confiável, o raio não → `_true_radius` cresce o raio enquanto o
  anel continua majoritariamente não-fundo (`_CIRCLE_EXTEND_MIN=0.80`). Medir em vez de votar.
- `tikz_generator._cmd_annulus_sector` desenha a cunha (`arc` externo → `arc` interno → cycle);
  `r_in=0` degenera em fatia de pizza, então o mesmo comando serve disco e coroa.
- **Guardas contra confete de arco:** a capa6 não tem círculo nenhum, mas o Hough dispara
  fantasmas nas diagonais dela. Três peças: coroa fina demais não carrega setor
  (`_CIRCLE_SECTOR_MIN_THICK=0.15·r` — matava um "anel" de 0.13cm), sliver < 25° é anti-alias e
  é absorvido pelo vizinho (varredura repetida: o sliver que caía em PRIMEIRO não tinha vizinho
  à esquerda), e se depois de tudo sobrou uma cor só, colapsa em círculo cheio. `_dedup_circles`
  também passou a comparar ÂNGULO (dois setores do mesmo anel têm mesma cor/centro/raio).
Medido: capa1 determinística 0.4339→**0.4641**; entregável **0.444→0.5331** (content 0.26→0.403).
capa1 renderiza de cache (OCR não-determinístico), então os setores foram MESCLADOS no
`vlm_analysis.json` dela pelo próprio detector — nada escrito à mão. **Teto restante da capa1:
o mosaico** (46% do erro; 3 tentativas já revertidas).

## Mosaico da capa1 — RESOLVIDO (2026-08-06), depois de 3 reversões históricas

O mosaico é uma grade regular de ~57px onde cada célula é vazia, sólida, ou dividida na
diagonal — **já dentro do vocabulário** (retângulo + triângulo). O que bloqueava era outra
coisa: `_detect_grid_blocks` projeta Sobel na moldura INTEIRA, então uma malha confinada a
uma coluna se dilui; e mesmo recuperando as linhas, a célula (3.2k px²) caía sob
`_MIN_REGION_AREA_FRAC` (6.5k px²) e era DESCARTADA. Novo passe `_detect_mosaic`, **ao lado**
da grade (nunca no lugar), com regra de área própria. Medido: capa1 **0.533 → 0.744**
(content 0.403→0.687); as outras 6 idênticas. Três coisas foram necessárias, todas medidas:
- **Achar o período: 3 formulações falharam antes da certa.** Autocorrelação crua e
  normalizada do perfil de TINTA saturam sempre no menor lag (o perfil é dominado por
  regiões grandes, não pela malha). O escore de PENTE sobre a energia de BORDA acerta a
  linha da capa1 (57) mas erra a coluna (trava nas bordas verticais fortes do anel). Solução:
  o pente é só uma **lista curta** de candidatos; quem escolhe é o **objetivo** — classifica
  as células com cada candidato e fica com o que mais encaixa.
- **"Só preencher o que a grade deixou VAZIO".** Sem isso a capa4 ganhava 332 peças por cima
  da grade que já a desenha (era o pior risco de regressão). Blocos de cor-de-FUNDO não
  contam como preenchidos — é justamente assim que a área do mosaico da capa1 fica livre.
- **Portão por ADJACÊNCIA, não por taxa global.** Taxa de encaixe sobre a capa inteira conta
  as células da coluna de TEXTO e afunda a malha real (capa1 dava 0.57 e reprovava). Mosaico
  é mancha CONECTADA: fica só a peça que tem peça vizinha, e o portão é `_MOSAIC_MIN_DIAG=8`
  peças diagonais sobreviventes. Isso mata o encaixe isolado por sorte (uma letra, um canto).
- Célula parcial na borda (a capa é CORTADA) é classificada nos pixels visíveis mas emitida
  com a geometria INTEIRA — o `\clip` da página apara. Sem isso faltava a 1ª fileira do topo.
- Célula cujo centro cai dentro de um disco detectado é pulada: ali é a curva do círculo, não
  um ladrilho (sem isso o anel ganhava um halo de quadrados).
- **Célula de DISCO (2026-08-06):** algumas células não são sólidas nem diagonais — são um
  quarto-de-círculo ou um semicírculo sobre o fundo. **Nenhum renderizador novo foi preciso:
  `_cmd_annulus_sector` com `r_in=0` já degenera em fatia de pizza.** 12 candidatos: quarto de
  raio=célula em cada canto, meio-disco de raio=célula/2 em cada aresta, e quarto de
  raio=célula/2 em cada canto — esta última família é a que pega o disco assentado num CANTO
  da malha, que aparece partido entre duas células (foi o semicírculo teal da capa1; sem ela
  os quartos de raio-cheio não achavam nada). Só emite quando o FORA da curva é fundo — o
  complemento de um disco não é primitivo, então uma volta colorida seria indesenhável.
  Medido: capa1 0.7727→**0.7961** (discordância de pixels 2.8%→1.9%); outras 6 idênticas.

## capa5 — o LOSANGO (2026-08-06): a forma vinha certa, a COR é que reprovava

capa5 é um X: 4 setores triangulares que se encontram no centro EXATO da capa (medido nos
pixels: cruzamento em 0.497W × 0.493H). O VLM já propunha os 4 — creme/esq, vermelho/topo,
cinza/base e o hachurado/dir — mas o gate REVERTIA o da direita (0.6326→0.6271), então os
retângulos da grade determinística ficavam expostos ali (24.8% da capa, o maior pedaço
faltante das 7). Causa: ele vinha pintado com o vermelho CLARO do setor de cima (#C43228)
quando a média medida daquele setor é #A24139 — a hachura o escurece.
- **`snap_region_colors` (edit_gate)**: rasteriza o polígono proposto, mede a cor real dos
  pixels que ele cobre e encaixa na paleta. Mesma divisão de trabalho do `snap_text_adds`:
  a proposta dá a GEOMETRIA, os pixels dão o VALOR. Média, mediana e cor-dominante foram
  comparadas antes de escolher a média — concordam onde importa (dir → #A23129 com 55% dos
  px; creme → #CFCCB5 com 41%, o creme do pôster é envelhecido). capa1/2/6/7: no-op.
- **Bandas medidas (`bands_cm`)**: quando um gradiente explica os pixels ≥15% melhor que uma
  cor chapada, o mesmo polígono é fatiado em 3–5 faixas (Sutherland–Hodgman), cada uma com
  sua cor medida. `apply_edit` emite uma região por banda. Baixa frequência → renderiza
  exato, sem o teto sub-pixel.
- **⚠️ O ganho veio de onde eu NÃO esperava, e a medição derrubou minha hipótese.** Eu
  previa que bandas capturariam a hachura; medido, o setor hachurado ganha só **5.7%**
  (6750→6368) — abaixo do portão — porque ali o resíduo é a TEXTURA dos traços, não o
  gradiente, e a paleta não tem cor perto de (134,47,39). Quem ganhou foi o **triângulo
  CINZA da base**, que tem gradiente vertical real: **23%** (4956→3815). Confirma de novo
  "contraste, não frequência" — agora com número para este setor.
Medido: capa5 0.6544 → **0.6956** (content 0.583→0.667). Fase A (cor) +0.009, Fase B
(bandas) +0.032. **Ressalva do olho:** a paleta só tem 2 cinzas, então o gradiente sai em
DEGRAU (uma borda horizontal visível onde as duas faixas se encontram) enquanto o original é
liso. Suavizar exigiria registrar cores intermediárias — que é o caminho do blend, já
revertido. Teto restante da capa5: a hachura, a moldura escura do pôster e o texto miúdo.

## `_drop_shadowed_grid` — a recíproca do "só preencher o vazio" (2026-08-06)

Depois que o anel e o mosaico passaram a desenhar a metade esquerda da capa1, os blocos
GROSSOS da grade continuavam lá embaixo — e a parte deles que sobrava PARA FORA da peça
medida pintava a cor errada: um quadrado cinza saindo do quadrante inferior-direito do anel,
um branco no inferior-esquerdo e um triângulo cinza fantasma no rodapé. Diagnóstico por
`diff_blobs` (manchas de discordância render×original, ranqueadas por área) + auditoria por
região. Regra nova: **aposenta o bloco de grade quando (a) um passe MEDIDO já é dono de ≥40%
dele E (b) ele acerta a cor em <40% do que ainda aparece.**
- **As DUAS condições são obrigatórias.** Só cobertura apagaria blocos honestos; só cor
  apagaria os TRIÂNGULOS honestos — a máscara aqui é o bbox inteiro, então uma metade
  legítima nunca passa de ~50% de acerto (medido: capa4 37–60%, capa6 45–60%). A condição de
  cobertura é o que mantém a peça INERTE onde não há mosaico/círculo: capa4 e capa6 têm 0%
  de cobertura medida, então nada é avaliado lá.
- Separação medida na capa1: blocos bons acertam 81–100%, os 6 culpados acertam 0–27%.
Medido: capa1 0.744→**0.7727** (content 0.687→0.728), discordância de pixels 4.7%→2.8%.
capa7 perde 3 blocos (inócuos, preto-no-preto) e fica **idêntica**; as outras 5 idênticas.

## `_detect_photo_margin` — a MOLDURA do pôster fotografado (capa5, 2026-08-06)

O North Star é "idêntico à IMAGEM", e a imagem da capa5 é a FOTO de um impresso: sobra a
margem de papel nos quatro lados (topo ~5px cinza 178, base ~6px quase-branco 235, esq ~7px
218, dir ~6px 207 — cores diferentes, é iluminação). Nós pintávamos arte até a borda; era o
maior erro restante dela (o `zone_board` dava BASE 68%, só a fileira de baixo ~48%).
**Assinatura que separa margem de design sangrado, medida nas 7:** a faixa é FINA nos QUATRO
lados (≤3% da dimensão) E CONTRASTA forte com o que há logo dentro (≥100 de distância RGB).
Um design que sangra ou tem "margem" larga (é o próprio fundo, dist≈0 — capa2 base 6.0%,
capa4 topo 6.1%, capa7 6.1%) ou tem distância pequena (é contínuo — capa6 dist≈2). Só a
capa5 satisfaz as duas; as outras seis falham em pelo menos um lado.
- **⚠️ A margem tem que ser desenhada por ÚLTIMO.** Na 1ª tentativa o Score não mexeu NADA
  (0.6956 → 0.6956): as regiões que o VLM adiciona são anexadas DEPOIS da análise, então os
  4 triângulos dele cobriam a moldura inteira. `tikz_generator._build_regions` faz uma
  partição estável levando `source=="margin"` para o fim; todo o resto mantém a ordem.
Medido: capa5 0.6956→**0.7205** (content 0.667→0.704); outras 6 idênticas.

## RESÍDUO — o sistema olhando o PRÓPRIO erro (2026-08-06, a peça de autonomia)

**O gargalo nunca foi vocabulário — era percepção do próprio erro.** Reveja como cada
detector nasceu hoje: EU rodei um diff, olhei o ranking de manchas, decidi o que cada uma
era, e escrevi o código. O sistema nunca soube que estava errado. Esse era o loop manual.
- `visual_comparator.residual_blobs(orig, render, canvas, top)` — manchas contíguas onde o
  render DISCORDA do original, ranqueadas por área, cada uma com bbox_cm e as duas cores
  (`ORIGINAL=#4CB5B3 vs NOSSO=#1F1F1E`). Abertura morfológica 5×5 para a franja de
  anti-alias de toda borda não virar "mancha".
- `vlm_proposer._residual_text` injeta essa lista no prompt: *"para CADA uma diga o que há
  ali no ORIGINAL e proponha o edit que corrige"*. Um mapa de ZONAS diz "este sexto da
  página está ruim"; uma mancha diz "nesta caixa o original é X e você desenhou Y".
- `replicate_cover._vlm_pass` calcula e loga o resíduo antes de chamar o Gemini.
**Provado ao vivo na capa5:** 8 edits (contra 12 do caminho manual), gate aceitou 7, mesma
qualidade. E o resíduo ACHOU UM BUG que eu tinha introduzido: marcou a margem direita
(`#CECDCA vs #C2362B`) — o Pass 1 do `\foreach` estava agrupando as duas margens VERTICAIS
num padrão e tilando fora da página. Corrigido (`source=="margin"` nunca vira padrão, mesma
família do bug círculo-como-retângulo): **capa5 0.7197→0.7534**.
**capa7 devolve ZERO manchas** — o sistema diz sozinho "esta capa está pronta". É o embrião
do critério de parada.
**ITERADO (mesma sessão):** `_vlm_pass` virou um LOOP — resíduo → propõe → gate → render →
resíduo, até `_RESIDUAL_ROUNDS=3`, ou até nenhuma mancha passar de `_RESIDUAL_MIN_PCT=0.15%`,
ou até uma rodada não landar nada. As rodadas são cacheadas (`{"rounds":[...]}`; cache antigo
de lista simples é lido como rodada 1). Duas peças foram NECESSÁRIAS, e a medição exigiu as
duas:
- **Dedup de `text.add` no aterramento.** Texto nunca casa pixel-a-pixel, então o resíduo
  segue marcando a área de texto como errada e o VLM RE-PROPÕE o bloco que ele mesmo já
  colocou. Sem isso a capa5 empilhou tipo em cima de tipo: rodada 3 re-adicionou os 3 blocos
  da rodada 1, **0.7605 → 0.7398**. Agora rejeita quando a 1ª linha já existe a <2cm.
- **Rede de segurança ENTRE rodadas — e ela NÃO pode ser hill-climb do Score cru.** 1ª versão
  revertia por Score e **jogou fora os 3 blocos de texto aprovados da capa6** (o Score é cego
  a tipo, texto certo sempre custa ~0.005). Discriminador que funciona: **`text_match`** —
  ADICIONAR texto sobe, DUPLICAR desce (a precisão cai). Reverte só se o Score caiu além de
  `_RESIDUAL_GUARD=0.005` E o texto não melhorou. Pegou a duplicata que escapou do dedup
  (0.7405 → volta pra **0.7543**).
- **O resíduo GUIA, nunca BARRA.** "Zero manchas" na rodada 1 pulava o passe inteiro do VLM
  na capa2 (0.3457→**0.3352**) — o detector de mancha é cego a tipo fino por construção
  (a abertura morfológica apaga). Resíduo vazio só é sinal de parada a partir da rodada 2.
**⚠️ As três guardas foram achadas por REGRESSÃO, não por raciocínio.** Cada uma quebrou uma
capa aprovada antes de eu perceber. Rodar as 7 depois de mexer no loop não é opcional.

## VETORIZADOR — testado e REJEITADO como caminho principal (2026-08-06)

Traçar contornos (`cv2.findContours` + `approxPolyDP` sobre a imagem quantizada na paleta)
e emitir polígonos. Medido nas 7: **ganha em 5 de 7 pela métrica** (capa1 0.796→0.862,
capa3 0.611→0.714, capa5 0.721→0.806) e **sem nenhum texto**. Mas o veredito do usuário
foi: capa1 um pouco melhor, **capa3 muito pior ("detector = full HD, vetor = 144p")**,
capa5 melhor. Três juízes independentes (cor pontual, cor com tolerância ±0..3px, F1 de
BORDA) preferem o vetorizador na capa3 — nenhum captura o que o olho vê ali.
**Rejeitado como caminho principal, e o motivo é o OBJETIVO, não a estética:** um vetorizador
é transcrição de uma passada. Não se auto-corrige (já é cópia), não conserta o próprio texto
(traça letra como mancha), não melhora com iteração, e a saída não é editável em termos úteis
(56 polígonos vs "mosaico de período 57"). Estrutura é o que torna auto-correção possível.
**Papel certo dele: rede de segurança LOCAL** — quando o VLM não souber nomear a forma de uma
mancha do resíduo, traçar o contorno DAQUELA mancha. A lacuna de vocabulário deixa de
bloquear. Ferramenta em `scratchpad/vectorize.py` + `render_analysis.py`.

## Lições / tentativas REVERTIDAS (não repetir do mesmo jeito)

- **⚠️ A FAMÍLIA DE BUG MAIS CARA DO PROJETO: "o pipeline calcula certo e o entregável não
  recebe" (três casos em três dias, 2026-08-19).** Nenhum foi achado olhando capa; os três
  vieram de conferir se o que SAI é o que foi DECIDIDO. Juntos valeram mais que qualquer
  feature da semana (capa11 +0.145, capa19 +0.050, capa14 +0.026, capa2 +0.015, capa6 +0.008).
  1. A análise vencedora só era gravada DENTRO do laço, antes de propor outro passe — quem
     saía cedo (platô/PASS/sem correção) deixava o `analysis.json` do estágio 1.
  2. `vlm_analysis.json` era lido de volta como ENTREGÁVEL PRONTO (ver acima).
  3. O ramo de PLATÔ faz `analysis = best_analysis` e quebra **sem re-renderizar** — então
     `cover.tikz`/`cover.pdf`/`render.png` podiam ser de um candidato REJEITADO enquanto o
     JSON guardava outro. Em capa3/16/18 **nenhum arquivo em disco reproduzia o render
     entregue**. Fix: re-renderizar a partir da análise que vai ser persistida, e tirar a
     `quality` reportada DESSE render.
  **Ferramenta de auditoria** (`scratchpad/audit.py`): para cada capa, compara o Score do
  `render.png` em disco com o Score de um render fresco do `analysis.json`. Delta ≠ 0 = bug
  desta família. Hoje: **20/20 idênticas**. ⚠️ **Rodar isto depois de mexer no orquestrador** —
  a classe é silenciosa por construção: o número sobe, o arquivo mente, ninguém percebe.
  ⚠️ Eu li a 1ª divergência ao contrário ("o número mentia para cima"); era o JSON que guardava
  a versão pior. **A auditoria diz que DIVERGE, não qual lado está certo** — re-rodar para saber.

- **⚠️ O CACHE DO VLM ERA BUG, NÃO DÍVIDA (2026-08-19).** O estágio 13 lia `vlm_analysis.json`
  de volta COMO ENTREGÁVEL PRONTO quando existia. O pipeline rodava inteiro — leitor
  estrutural, seleção de camadas, calibração — e no fim **descartava tudo** e carregava um
  retrato antigo. **Nove capas ficaram congeladas assim** (1, 2, 5, 6, 7, 14, 15, 17, 19).
  Eu tinha registrado isso aqui em 18/08 como "cache obsoleto, recomputar custa API" — leitura
  errada: não era dívida, era curto-circuito. Mesma família do bug de persistência do A0.
  **Fix:** `_vlm_pass` sempre roda; ele reusa `vlm_edits.json` (as PROPOSTAS — zero API) e
  re-julga cada edit contra a análise fresca. O `vlm_analysis.json` continua sendo ESCRITO
  como registro/restauração, nunca lido como resposta.
  Medido: capa19 0.8698→**0.9194**, capa14 0.5890→**0.6150**, capa2 0.5661→**0.5806**,
  capa6 0.9425→**0.9500**, capa17 0.8396→0.8416; capa5/7/15 estáveis.
  **Custo:** ~2min → 10–14min por capa (re-render por edit). Aceitável no regime de uso
  (1–2 capas por rodada, computação livre).
  ⚠️ **capa1 é a exceção e foi RESTAURADA à mão:** o entregável dela é cirurgia manual, e sem
  o curto-circuito ela cai 0.8168 → **0.7342** (o OCR volta a ler o anel como "6"). O número
  AUTOMÁTICO honesto da capa1 é 0.7342; o 0.8168 é manual e está marcado como tal.

- **CALIBRADOR: a alavanca era a ERRADA (achado + fix 2026-08-18).** Ele nasceu com um único
  controle de tamanho, `hscale`, que estica o tipo de LADO. Quando o texto está simplesmente
  pequeno/grande demais ele "conserta" achatando lateralmente até o teto 1.4 — e o
  hill-climbing REJEITA, corretamente, o tipo distorcido. Por isso a calibração nunca aparecia
  no Score. ⚠️ Em 06/08 eu vi isso na capa2, diagnostiquei como "medição suja" e pus o guard de
  `clipped`. **Era sintoma; a causa era a alavanca.** Agora o tamanho vem de `font_size_pt`
  dirigido pela **ALTURA** — o eixo que não depende da STRING (e a string pode divergir: o
  produto traz o próprio texto, só o tipo precisa bater). `hscale` só entra DEPOIS que a altura
  está certa, onde um resíduo de largura é tracking de verdade. Duas peças de medição
  acompanharam: `_row_band` (mede na banda da própria linha — a vizinha vira outra banda em vez
  de contaminação) e `_MARGIN_Y_CM` 0.10→0.30 (a bbox vem DA tinta, então o próprio glifo
  encostava na borda e era descartado). Medições utilizáveis 10/54 → 43/79.
  Medido: capa10 0.7916→**0.8017**, capa8 0.9173→**0.9205**, capa13 0.9159→**0.9183**;
  capa4/6/7 idênticas. **Teto restante: capa15 e capa19 ficam 0 medições mesmo com 1cm de
  folga** — o tipo é enorme (caixas 2.3–2.7cm) com entrelinha apertada, os glifos SE TOCAM e
  tudo vira uma banda só. Margem proporcional foi testada (frac 0.15/0.25/0.40) e não move.

- **Transação no portão — MORTA DUAS VEZES, a segunda com o caso ideal (2026-08-19).**
  Na 1ª rodada de VLM da capa3 (juiz novo, 1 rodada), o Gemini propôs **6 `region.remove` +
  6 `region.add ellipse`** — semanticamente CERTO: capa3 é op-art de círculos e os blobs
  traçados deveriam ser elipses; é o defeito que o usuário chamou de "parece um borrão". O
  portão rejeitou tudo, um a um, e eu ia usar isso como a prova de que faltava transação
  (remover sozinho piora, adicionar sozinho piora, só o PAR ganha). **Medi antes de construir:
  aplicando os 12 juntos, capa3 vai de 0.6146 para 0.3887.** As elipses propostas não batem
  com o lattice (uma começa em x=-0.5, fora da página). A proposta era boa em INTENÇÃO e
  ruim em GEOMETRIA, e o portão por-edit chegou na resposta certa.
  **Não construir transação sem antes aplicar o grupo e medir** — a história é convincente e
  a medição a derruba.
- **Transação no portão (hipótese MORTA, medida 2026-08-18):** eu ia agrupar edits para o gate
  poder atravessar um vale (remover glifo traçado + inserir texto só funciona em PAR). Medi a
  classe antes de escrever: regiões traçadas pelo leitor que caem DENTRO de caixas de texto
  existem em **3 de 20 capas** (5, 14, 17), cobrindo 2–9% de cada uma → ganho médio estimado
  ~0.01 nas 20. **Não vale mudança arquitetural.** A peça fica descrita aqui caso a classe
  cresça; o número é o portão.
- **⚠️ ONDE ESTÁ O ERRO, medido nas 20 de uma vez (2026-08-18) — fazer ISTO antes de escolher
  trabalho.** Somando a discordância de pixels das 20 e partindo por dentro/fora das caixas de
  OCR: **TEXTO 49%, FORMA 51%**. O texto concentra em 7 capas (10, 15, 17, 14, 19, 8, 13 = 59
  dos 76 pontos). Foi essa medição que provou que a capa10 é texto e não barras — uma
  suposição minha que já estava escrita como fato nesta doc. **Medir a distribuição do erro é
  barato e derruba palpite; fazer antes de escolher o que atacar.**

- **Bug do `\foreach` desenhando círculo como retângulo (capa7, +0.21 Score):** o
  atalho de padrão em `tikz_generator` (Pass 1) emitia `rectangle` INCONDICIONALMENTE,
  então todo círculo/triângulo que pegava um `pattern` do `pattern_detector` virava
  BLOCO — e no anchor do "mirror", fora do lugar real. Os "retângulos do grid" na
  fileira de círculos da capa7 eram, na verdade, círculos mal-renderizados. **Fix:**
  Pass 1 só consome `rectangle`/`polygon`; círculo/triângulo cai no Pass 3 e é desenhado
  na própria bbox. capa7 0.668→0.874, zero regressão nas outras 6. **Como foi achado:**
  tentei um dedup "descartar célula de grid sob círculo de mesma cor" — REGREDIU
  (0.668→0.515), e o render regredido expôs que os círculos iam pro lugar errado → o
  culpado não era o grid, era o `\foreach`. A reversão apontou o bug real.
- **Preencher OCLUSÃO no leitor (capa10, 2026-08-17):** o laranja da capa10 é um ANEL em
  volta do vermelho (fill 0.68 do bbox), então chega como tiras laterais que nenhum primitivo
  descreve e renderiza serrilhado. Hipótese: preencher o buraco quando outra COR o ocupa
  (≠ quando é o FUNDO, aí é anel de verdade) e deixar o vermelho repintar por cima. **Não
  alcançou a capa10** — as tiras são componentes SEPARADOS, não anel fechado, não há buraco —
  e custou capa16 0.879→0.870 e capa18 0.682→0.662 (juntou peças que devem ficar separadas).
  Revertido, com a nota no `structural_reader`. **O conserto tem que JUNTAR AS TIRAS.**
  `rounded_rect` está fiado no leitor e hoje é INERTE (nenhuma capa o escolhe).
- **Mosaico fino de triângulos (capa1):** detector funcionava mas REGREDIU o SSIM
  (alta-frequência pune desalinhamento sub-pixel, igual texto pequeno). Revertido.
  ⚠️ **A LIÇÃO ENVELHECEU:** a Fase 6 mostrou que alta-frequência NÃO era o teto — o mosaico
  da capa18 (86 triângulos) e a malha da capa16 renderizam bem quando o primitivo carrega a
  própria orientação. O que travava era expressividade, não frequência.
- **Blend fallback (média chapada p/ hachura/mosaico, primitivo NOVO `shape=blend`):**
  a hipótese era que um campo de alta-freq. mal-renderizado ficaria melhor como sua MÉDIA
  medida (retângulo sólido, cor medida do original → registrada na paleta, sem penalidade
  sub-pixel). Construído inteiro (tikz dispatch + `_mean_hex`/`_register_color` +
  aterramento isento-de-paleta + resolução no `run_gate`) e MEDIDO nos dois alvos: capa5
  metade-dir 0.6624→**0.5354**, capa1 mosaico 0.4369→**0.3794** (coluna) / **0.3125**
  (metade). TODOS revertidos pelo gate. **Causa medida (scan de uniformidade por célula):**
  o teto restante NÃO é alta-FREQUÊNCIA (que a média resolveria) e sim alto-CONTRASTE
  colorido (mosaico = triângulos distintos std 83-98; hachura = vermelho+branco+escuro). A
  média CHAPADA apaga a estrutura → cada pixel erra pelo std interno (grande); o render
  estruturado, mesmo imperfeito, acerta mais. Duplo-vínculo: estruturado demais p/ média,
  fino demais p/ tiles (teto sub-pixel). Revertido inteiro (nunca-pior segurou). **Lição:
  medir a UNIFORMIDADE da zona antes de propor um blend — só ganha em campo genuinamente
  uniforme, e nenhuma das 7 tem um mal-renderizado.**
- **Setores angulares de círculo (capa1, primitivo NOVO):** o vocabulário de círculo
  só fazia anéis radiais; o alvo da capa1 tem quadrantes angulares (teal/vermelho/branco)
  que a mediana radial vira disco cinza. Construí o primitivo (amostra por ângulo →
  cunha `\fill (cx,cy) -- ++(a0:r) arc (a0:a1:r) -- cycle`). **Detecta certo** (3 setores),
  mas o Score não subiu (0.4339→0.4334): o alvo é só 9% do foreground e a versão mínima
  (cunha cheia, sem anéis internos, dropa o 4º quadrante) renderiza pior que o disco.
  Revertido; o primitivo fica no histórico. **Lição:** o zone_board provou que o alvo NÃO
  era o gargalo — medir a zona antes de crescer o vocabulário.
- **Reconciliação texto×círculo "o maior vence" (capa7 BRAUN, Fase 4):** o alvo falso
  (anéis TINY r=0.5cm que o Hough alucina sobre "BRAUN") fazia o assembler dropar o
  texto BRAUN (conf 0.81). Regra medida: círculo menor que o texto → anel falso (dropa
  círculo, mantém texto); círculo maior → glifo mal-lido (dropa texto, capa1 "6" no
  alvo r=2.2cm). Semanticamente CERTA e o size-gate separa os casos. Mas REGREDIU:
  capa7 0.874→0.870 (o BRAUN é fonte-logo condensada → renderiza gigante e VAZA, igual
  ao texto da capa1) e a área é minúscula (topo-dir) = wash; capa1 perdeu 2 círculos
  reais. Revertido. **Mesmo teto de renderização de texto** — recuperar texto miúdo/
  condensado não bate a métrica. Todo o resto (capa1/2/6/7) esbarra nisso → é o VLM.
- **Grade adaptativa p/ o mosaico (capa1):** medi que a malha do mosaico é regular
  (~57px) mas a projeção Sobel GLOBAL dilui e perde linhas locais (col 173). Recuperei
  linhas por faixa (só pico agudo = linha reta, rejeita diagonal larga). REGREDIU
  0.4339→0.4056: as células novas caem abaixo do `min_cell_area` e são DESCARTADAS → o
  mosaico evapora. Revertido. **Conclusão medida (não suposta):** o mosaico da capa1 é
  teto determinístico — células pequenas vs. filtro de área + diagonais sub-pixel.
- **Corte VERTICAL na altura toda quando sem texto (irmão do horizontal):** tentei
  aplicar `graphic_rows = h_px se não há texto` ao corte de linhas verticais (0.65),
  esperando o mesmo ganho do horizontal. REGREDIU capa5 0.612→0.444 (o triângulo grande
  + "grafik" no rodapé disparam linhas verticais fantasma que estilhaçam a grade);
  capa3 ficou igual. Revertido. **Lição:** nem toda heurística cega é ruim — o corte
  vertical é load-bearing. O horizontal era removível porque só o rodapé era o problema;
  o vertical protege contra fragmentação real. Medir SEMPRE antes de generalizar por analogia.
- **Filtro de "suporte de linha" (capa6):** separava linha real de haste de texto,
  mas removia linhas de grade PARCIAIS legítimas → regrediu capa5/6/7. Revertido.
  → Fix cirúrgico certo: mascarar zonas de texto ANTES da projeção Sobel.
- **Aspect ratio derivado da imagem:** SSIM-neutro (pipeline é proporcional) mas
  mantido por fidelidade real de forma.
- **Regra geral:** "parece certo no overlay" ≠ "melhora a métrica". Medir com o
  portão de regressão SEMPRE antes de manter. Já houve 2 reversões — é normal.

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

Em `cover_assembler.py`:
- `_TEXT_BOX_PAD_PX = 4` — a máscara do mapa de layout cresce a caixa de OCR 4px.
  Com 2px a borda de gradiente do ÚLTIMO glifo ficava fora da máscara → linha vertical
  fantasma na borda direita da caixa (o 'd' do "rancid" virava coluna espúria em x=19.2
  que espremia as diagonais). 4px cobre; só a busca-de-linha é mascarada, então a caixa
  maior não toca a classificação de cor. Ganho: capa6 0.889→0.926, zero regressão.

Fonte: cadeia Helvetica → **TeX Gyre Heros** (clone métrico, letterforms batem) →
Arial. Não há Helvetica real no Windows; Arial tem letterforms diferentes.

## `automation/tools/` — diagnóstico e manutenção (ver o README de lá)

Fora do pipeline. `diff_blobs.py` (manchas de discordância ranqueadas — é como se acha a
causa de "está estranho" sem chutar), `render_analysis.py` (renderiza+mede qualquer analysis
com a máquina real), `vectorize.py` (o vetorizador rejeitado, guardado como rede de segurança)
e **`merge_capa1.py`, que é NECESSÁRIO para regenerar a capa1** — ela renderiza de cache
porque o OCR dela é não-determinístico, e sem esse script ela não é reproduzível.

**`run_batch.py` — rodar várias capas com PROGRESSO VISÍVEL.** Uma rodada leva dezenas de
minutos e era invisível até terminar. Ele escreve `output/replicated/_run_status.md` a cada
capa (barra, fila, tempo, ETA, média parcial) — dá pra deixar aberto no editor:
```bash
python automation/tools/run_batch.py refresh=5,7 vlm=1,2,6 plain=3,9,10
#   plain = só determinístico · vlm = reusa o cache (sem API) · refresh = chama o Gemini
```
Ele **RECUSA rodar a capa1 em `plain`** — foi o erro que derrubou o entregável dela de
0.796 pra 0.603.

**`content_match_tol` é OPT-IN** (`SWISS_TOL_METRIC=1`): custa 0.2–1.0s por comparação e o
Score ainda não a consome, então ligada por padrão seria desperdício puro no loop do gate.

## Método: o USUÁRIO narra, eu acho no código (2026-08-19, funciona — usar isto)

O usuário descreve o que vê de errado numa capa; eu localizo a causa NO CÓDIGO, meço, e
fecho. Provado: ele perguntou *"um círculo é um círculo, por que numa fica bom e noutra
ruim?"* → causa exata (`_MAX_POLY_PTS` era 12, o que dá 7.6px de desvio num disco de r=100)
→ correção → **5 capas subiram, 0 caíram**. Foi o ganho mais limpo da semana.

**A regra que faltou e custou uma rodada:** quando a narração revela VÁRIOS defeitos, fechar
os de causa conhecida e correção barata ANTES de atacar o difícil. Na capa10 saíram 4
defeitos, eu fui direto no mais difícil (o "UUU") e fechei ZERO. Um defeito por vez, até o fim.

**Estados legítimos:** ABERTO · FECHADO (com a medição) · **BLOQUEADO por X** (resposta
válida — registra o motivo e libera o próximo) · **NÃO É CLASSE** (a medição mostrou que o
defeito é local, não geral, e não vale mudança global).

### Registro de defeitos — rodada das 20 (narração do usuário, 2026-08-19)

- **A2 capa3 — o lattice perdeu para o leitor. DECIDIDO: o PORTÃO É SOBERANO.** O
  `circle_lattice` dispara normalmente (período 5.36cm, raio 3.75cm, 16 lentes medidas) e
  produz um render visualmente MUITO mais próximo do original — mas perde a votação por 0.19
  (leitor 0.799 × lattice 0.611). Antes da Fase 6 eu o mantinha à mão, contra a métrica
  ("mantido pelo OLHO", registrado quando o construí); quando o `_select_reader` virou
  automático, a métrica ganhou. **O usuário decidiu manter o portão soberano** e procurar uma
  saída melhor em vez de abrir exceção. Testado e descartado no caminho: raio (0.70·período
  já é o ótimo; 0.50/0.55/0.60 pioram) e os dois juízes (o novo prefere o leitor por margem
  AINDA MAIOR). O `structural` é o único sinal que prefere o lattice (0.479 × 0.427).
  **É o caso-teste de qualquer juiz futuro: acertá-lo sem quebrar as outras 19.**
- **⚠️ 19 regras de descarte SEM MEDIÇÃO no pipeline (varredura 2026-08-19).** Três já
  cobraram caro (`min(m.shape)<4` comia toda régua; `_suppress_text_in_shapes` comia texto em
  círculo; `dedup_text` comia texto por vizinhança) e as três eram a MESMA forma: uma regra
  escrita para um caso, apagando coisa legítima em outras capas, sem medir nada. As demais
  candidatas estão em `ocr_extractor` (`conf < 0.50` derrubou 'SWIIS' 0.30 e 'Bi 8' 0.13;
  `h_box_cm < 0.15`) e nos guards de círculo do `image_analyzer`. **Padrão de busca que
  funciona: `grep -B1 continue` atrás de `if` com limiar.**

- **A3 costura branca entre formas (capa8/11/12, "círculo picotado"). FECHADO.** O leitor
  traça cada cor separadamente, e os pixels de anti-alias da fronteira ficam FORA dos dois
  contornos → o FUNDO aparece numa fresta de 1–3px. Medido: fundo invadindo 8.47% da página
  na capa3, 2.42% capa13, 2.13% capa8, 1.63% capa12. `_SEAM_BLEED_PT` 0.5→**1.0pt** (varredura
  0.5/1.0/1.5/2.0: em 1.0 a capa13 tem seu máximo 0.919→0.930 e a capa4 quase não sente;
  acima disso as formas incham e os dois controles caem). Medido nas 10 determinísticas:
  capa18 +0.016, capa13 +0.010, capa20 +0.010, capa16 +0.008, **saldo +0.044, zero regressão
  real.** ⚠️ Na capa3 a sangria só tira 8.47%→7.99% — lá o buraco **não é costura**, é
  conteúdo faltando (ver A2).
- **A1/A5 texto sumindo — DUAS causas, ambas regras CEGAS, ambas removidas.**
  1. **FECHADO.** `cover_assembler._suppress_text_in_shapes` descartava TODO texto cujo centro
     caísse dentro de um círculo detectado. Nasceu do anel da capa1 lido como "6". Mas texto dentro
     de círculo é recurso suíço padrão: a capa11 perdeu "THE MOST / SPECIAL / YOU" — conf
     0.86–1.00, tinta 0.385cm, passando por TODOS os filtros — e ficou com **zero textos**.
     **Removida**: o `_select_text` faz a mesma pergunta MEDINDO (remove → renderiza → só
     mantém a remoção se o Score sobe). A regra cega virou redundante no dia em que a medida
     existiu, e ninguém percebeu.
  2. `edit_gate.dedup_text` removia leitura do OCR por VIZINHANÇA. Na capa17 o VLM adicionou
     "SWISS" com caixa de 16.8×4.5cm cobrindo as DUAS linhas do título, e o "STYLE" — lido
     com **confiança 1.00** — morreu por estar embaixo. Agora exige as **mesmas palavras**:
     o dedup existe para remover a leitura que o VLM SUBSTITUIU; palavra diferente é texto
     diferente.
- **⚠️ O QUE A TROCA "regra cega → portão medido" COMPROU E O QUE NÃO (medido 2026-08-19).**
  Removida a regra do círculo: **capa11 recuperou os 3 textos** ('THE MOST'/'SPECIAL'/'YOU')
  e subiu 0.9438→**0.9463**; capa7 0.9237→0.9273; capa1 fica em **0.7346 com ou sem** a regra.
  **MAS o `_select_text` NÃO reproduz o acerto dela:** o "6" da capa1 É testado (13.6% da
  página, 411pt) e o portão decide **MANTER** — remover baixa o Score, o mesmo ponto cego do
  "UUU" da capa10 (glifo falso escuro sobre área escura erra menos que expor o fundo).
  Saldo: a regra cega custava uma capa inteira e não comprava nada mensurável → removida.
  O "6" só sai quando o juiz melhorar; a máquina certa já está no lugar, inerte.
- **A4 capa19 "the shining atrás do retângulo". NÃO é ordem de desenho** — texto sempre sai
  depois das regiões (tikz_generator L161 vs L168). No original **"the" é BRANCO** (sobre a
  forma preta) e **"shining" é ESCURO** (sobre o amarelo); o OCR entrega UM elemento com UMA
  cor, então metade some. Precisa de cor por trecho. ABERTO.

### Registro de defeitos — capa10 (a primeira rodada do método)
- **D1 "UUU" — o OCR lê o GRÁFICO como texto.** EasyOCR lê os 3 hot dogs como as letras
  "UUU" a **351pt**, conf 0.65 — MAIOR que a de duas legendas reais da mesma capa (0.62).
  Mesma falha do "6" a 411pt da capa1. Construí `_select_text` (portão medido: remove o
  elemento, renderiza, mantém a remoção só se o Score sobe — mesmo padrão do `_select_layers`).
  Funcionou e **decidiu MANTER**: sem o UUU o Score CAI 0.7979→0.7565, porque preto-onde-é-
  vermelho-escuro erra menos que bege-onde-é-vermelho-escuro. **BLOQUEADO pelo juiz.** A peça
  fica: é a máquina certa, hoje inerte, e passa a agir sozinha quando o juiz melhorar.
  ⚠️ **Duas hipóteses de heurística foram MEDIDAS e MORTAS nas 20** — não repetir:
  (a) "glifos estilhaçam em muitos componentes" → INVERTIDO (texto real vira UM blob na
  resolução do original; o UUU falso tem 5); (b) "gráfico está coberto por formas traçadas"
  → INVERTIDO ('rancid'/'grafik'/'theshining' dão cobertura 1.000; o UUU dá 0.113).
- **D2 régua fina descartada. FECHADO — e o ganho foi MUITO maior que a capa10.**
  `m.shape[0] < 4 or m.shape[1] < 4` no leitor exigia 4px nos DOIS eixos, então descartava
  todo componente FINO de TODAS as capas — não só os separadores da capa10. Uma régua é fina
  num eixo e longa no outro, e design suíço vive delas. Fix: julgar por ÁREA e rejeitar só o
  que é pequeno em todas as direções (`min<2 or max<4`).
  Medido nas 11 determinísticas, **zero regressões**: capa18 0.6935→**0.7687** (+0.075),
  capa20 0.8387→**0.8801**, capa11 0.9070→**0.9457**, capa16 0.8904→**0.9096**,
  capa8 →0.9318. Média das 20 **0.833→0.842**, capas ≥0.90 de 9 para **10**.
  ⚠️ A capa10 — que motivou a busca — ganhou ~zero. **O defeito era geral e a capa que o
  revelou não era a que mais sofria dele.** É o argumento a favor de medir nas 20 sempre.
- **D3 3ª tira com laranja divergente. NÃO É CLASSE.** Medi o par de cores mais próximo nas 20
  paletas: capa10 dá **69.6**, uma das MAIS separadas (mediana 36.4; capa15 6.4, capa20 12.1).
  Fundir cores próximas por limiar mexeria em 11 capas pra consertar uma tira. Não entra.
- **D4 anel vira tiras laterais** — ABERTO (ver Reversões: preencher oclusão foi revertido).

⚠️ **USO DO VLM (2026-08-19):** só 9 das 20 capas JÁ TIVERAM um passe (1,2,5,6,7,14,15,17,19).
**Onze nunca viram o VLM** (3,4,8,9,10,11,12,13,16,18,20). E as 9 foram propostas contra
renders que não existem mais (pré-leitor-estrutural). Os edits cacheados são re-julgados, mas
a PROPOSTA é velha. Re-propor custa API — priorizar por capa, nunca em lote.

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

**Um loop otimiza dentro do vocabulário; ele não inventa vocabulário novo** — mas o
vocabulário DEIXA de ser estático na Fase 5: primitivos paramétricos (polígono geral)
+ a fila `vocab.gap` fazem ele crescer por demanda medida (ver "VLM — integração").

## Divisão de trabalho

- **Loop (auto)** — calibração por elemento (escala/posição medidas do render), patch
  de cor, busca entre alternativas de forma. Hill-climbing: aceita só se melhorou.
- **VLM (proponente no loop, Fase 5)** — propõe EDITS TIPADOS (dado, nunca código):
  corrigir string que o OCR errou, mover/recolorir/redimensionar, apontar `vocab.gap`.
  Todo edit passa pelo GATEKEEPER (aterramento + portão medido). Roda no platô.
- **Dev (humano)** — crescer o vocabulário-CÓDIGO (primitivos), atender a fila de
  `vocab.gap`, corrigir bugs de algoritmo. Tudo com portão de regressão das 7 capas.

## Fora de escopo (NÃO fazer sem pedido explícito)

- Mexer em `styles/`, `brands/`, `vision_extractor.py` ou no template do livro —
  são de outro fluxo, não do replicador. **A integração do VLM (Fase 5) mora num
  módulo NOVO no fluxo do `cover_assembler`/`replicate_cover`, NÃO no vision_extractor.**
- Refatorar/renomear módulos que não têm bug.
- Perseguir SSIM > 0.95 com micro-tuning.
- Commitar, dar push ou criar PR sem o usuário pedir.
- Criar arquivos novos (docs, scripts) sem necessidade — preferir editar o existente.
- **RECONSTRUIR LOGOMARCAS.** O North Star manda "identificar se há logo (sim/não),
  NÃO adicionar/reconstruir". As marcas gráficas (o 'v' da versatus em capa1/2, BRAUN
  em capa7) são GRÁFICO, não texto — tentar replicá-las (OCR lê como texto, CV desenha
  o 'v') é ato falho e desperdício.

**LOGO — placeholder "Name (Logo)" (feature de 2026-08-03, orientação do usuário):** logo
NÃO se reconstrói; o sistema RECONHECE e mostra um placeholder que PROVA o reconhecimento.
Edit tipado **`logo.mark {name, bbox_cm, hex}`** (`edit_gate`): o VLM PROPÕE (prompt do
`vlm_proposer`: marca gráfica → `logo.mark` com o nome, NUNCA text.add/region.add/redesenho);
`apply_edit` REMOVE regiões+textos na bbox (a marca derretida + o wordmark), escreve
**"<Name> (Logo)"** e registra a bbox em `analysis["logos"]` (gancho pro passo FUTURO de
inserir a imagem real — `convert_logos.py`+`brands/`, OUTRO BLOCO, não agora). Está em
`_TRUST_OPS` (remove lixo + placeholder → não piora). Provado manual na capa7 ("BRAUN" texto →
"Braun (Logo)"). Serve capa7 (Braun), capa1/capa2 (o 'v' da versatus → "Versatus (Logo)").
`image_analyzer._detect_logo` (~L949) segue devolvendo só `bool` (has_logo INERTE) — o
reconhecimento agora vem do VLM, não da heurística de variância.
