# doc-pipe — Como funciona o Swiss Cover Replicator

> Documento de estudo. Explica **o que o sistema é**, **como o pipeline está montado**,
> **como ele se corrige sozinho**, **como medimos**, e **onde estão os limites reais**.
> Escrito para quem quer entender o projeto de ponta a ponta, não só rodar.
>
> Última reescrita: **2026-09-09** (Fase 7 — integração capa + conteúdo).
> A revisão de 18/08 descrevia sete capas e um sistema sem integração. A versão anterior descrevia o
> sistema antes da **Fase 6** — um detector por forma e um juiz cego a texto. As duas coisas
> mudaram; ver §3 e §4.

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
  → ocr_extractor.py       EasyOCR + medição de TINTA: bbox, baseline, tamanho, peso, cor.
                           Roda PRIMEIRO — entrega as caixas de texto a todo o resto.
  → structural_reader.py   O LEITOR GENÉRICO (Fase 6). Quantiza na paleta → componentes
                           conexos por cor → escolhe o primitivo que melhor EXPLICA os
                           pixels (IoU) → separa blobs que nenhum primitivo explica.
  → image_analyzer.py      Os DETECTORES (grade, círculos, lattice, mosaico, margem).
                           Continuam vivos: o portão do estágio 7 escolhe quem entrega.
  → pattern_detector.py    repetição/simetria → \foreach
  → font_matcher.py        família/peso (peso vem do stroke_ratio medido)
  → cover_assembler.py     ORQUESTRA a ordem (OCR→CV) e junta tudo → analysis.json
  → tikz_generator.py      JSON → TikZ determinístico (sem LLM)
  → replicate_cover.py     LuaLaTeX ×2 → PDF → PNG → compara → LOOP de correção
  → visual_comparator.py   métricas + mapa de diff + manchas de resíduo
  → calibrator.py          mede a tinta do render vs original → correção por elemento
```

### O leitor genérico (Fase 6 — a mudança que mais importou)

Até 2026-08-16 cada forma tinha seu detector, e cada um foi calibrado até as 7 capas
originais pararem de regredir. Quando o conjunto foi para 20, **metade das novas falhou**:
uma grade de quadrados colapsou, um mosaico de triângulos não disparou, uma malha de losangos
sumiu. Era overfitting num conjunto de treino de 7.

O leitor faz o mesmo trabalho **medindo**: os componentes conexos de cada cor **são** o
ladrilhamento, seja ele grade, mosaico ou lattice; e para cada um o sistema rasteriza
retângulo, círculo, elipse, retângulo arredondado e o contorno traçado, ficando com o de
**maior IoU**. O IoU do vencedor é a confiança, de graça.

Ele não sabe o que é uma grade. Periodicidade e ritmo caem fora dos próprios componentes.

Duas coisas que os pixels sozinhos erram, ambas tratadas: as caixas do OCR são **mascaradas**
antes de traçar (senão as letras voltam como poliguinhos debaixo das próprias palavras), e
formas que se **tocam** são separadas por distance transform + watershed.

### Seleção de camadas e de leitor (confiança MEDIDA)

O leitor entra **ao lado** dos detectores, nunca no lugar: o estágio 7 renderiza os dois e
fica com o melhor (`_select_reader`). Depois, cada camada de detector é derrubada em turno e
só some se o Score melhorar sem ela (`_select_layers`). É assim que uma capa sem grade real
(capa7) se livra da grade imposta, e como a capa4 mantém os detectores que ainda a servem
melhor. **16 de 19 capas passaram a preferir o leitor.**

---

## 4. O juiz — como medimos

Autoridade: `visual_comparator.py`.

| métrica | o que é | meta |
|---|---|---|
| **`score`** | **`0.30·SSIM + 0.50·content_effective + 0.20·content_iou` — o que o loop otimiza** | ≥ 0.95 |
| `structural_match` | casa as FORMAS uma a uma (cor, área, centroide, Hungarian). Calculado e REPORTADO, fora do Score — ver abaixo | diagnóstico |
| `ssim_global` | SSIM skimage | ≥ 0.95 |
| `content_match` | qualidade SÓ nos pixels de conteúdo (não-fundo) | → 1.0 |
| `content_iou` | sobreposição das máscaras de conteúdo | → 1.0 |
| `text_match` | F1 da tinta nas caixas de OCR, **tolerante a desalinhamento** — o portão de TEXTO | → 1.0 |
| `content_match_tol` | `content_match` com tolerância de ±2px. **OPT-IN** (`SWISS_TOL_METRIC=1`) | diagnóstico |

### ⚠️ SSIM sozinho engana

SSIM é ponderado por ÁREA. Uma capa com fundo grande ganha SSIM alto só acertando o fundo.
capa2 tem SSIM 0.94 e `content_match` 0.03. **Sempre olhe os dois juntos.**

### O juiz foi calibrado contra o olho — e a troca foi REVERTIDA no mesmo dia (2026-08-19)

O usuário classificou as 20 capas em **Boas**, **Ok** e **Péssimas**. Isso virou o alvo: sobre
os **123 pares de classes diferentes**, com que frequência a métrica ordena como ele ordenou?

| sinal | concordância |
|---|---|
| **SSIM sozinho** | **80.5%** |
| casamento de formas (`structural`) | 76.4% |
| o Score anterior (0.30/0.50/0.20) | 71.5% |
| `content_match` | 71.5% |
| **`text_match`** | **51.2% — acaso** |

`0.75·SSIM + 0.25·structural` dá **82.9%** e preserva 4/4 no banco adversarial antigo — passou
nos dois testes que existiam. **E mesmo assim teve de ser revertido.**

Com o loop otimizando por ele, quatro capas pioraram visivelmente: duas perderam blocos de
texto, uma perdeu um título de 102pt, outra virou um borrão chapado. **Mecanismo:** nem o SSIM
nem o `structural` percebem TEXTO FALTANDO — o primeiro mal reage a tipo fino, o segundo casa
blobs coloridos. Sem nenhum termo de conteúdo, **apagar texto virou de graça** e o loop apagou.

⚠️ **A lição vale mais que os pesos: uma métrica pode ser um bom RANKEADOR e um péssimo ALVO DE
OTIMIZAÇÃO.** Concordância de ordenação não é teste de aceite suficiente — é preciso rodar o
loop com a candidata e OLHAR os renders. Qualquer Score futuro precisa das duas coisas: algo
que ordene como o olho E algo que puna conteúdo ausente.

⚠️ **Duas doutrinas deste documento envelheceram e foram corrigidas por esta medição:**
"SSIM sozinho engana" era verdade quando faltava conteúdo inteiro — com a estrutura certa,
inverteu. E o `text_match`, adicionado ao Score um dia antes, mede algo que o usuário não usa
para julgar (*"sobre o conteúdo do texto, meio que foda-se"*). **Medição envelhece; re-meça
antes de construir em cima.**

⚠️ Os pesos exatos **não são identificáveis** com 20 capas (só 3 combinações ficam a 2pp do
topo). O que é robusto é a direção: SSIM domina.

**O que a troca chegou a destravar (e foi junto na reversão):** o portão que remove texto inventado pelo OCR (`_select_text`)
estava inerte — com o juiz antigo, apagar o "UUU" que o OCR leu nos hot dogs da capa10 PIORAVA
a nota. Com o juiz novo ele apagou sozinho, sem código novo.

### (histórico) O juiz medido contra o olho — a hipótese que não sobreviveu

Existe um **banco de provas** (`scratchpad/judge_bench.py`) com os casos em que o usuário deu
veredicto: vetorizador × detector nas capas 1/3/5, e a capa11 com figura e fundo trocados.
Uma métrica passa quando ordena o par como a pessoa ordenou.

| | `score` | `ssim` | `content_match` | casamento de formas |
|---|---|---|---|---|
| concordância | **4/4** | 3/4 | 3/4 | 3/4 |

O Score **acerta os quatro**. O caso que por muito tempo foi citado como prova de juiz
quebrado — "o lattice fiel da capa3 perde para a grade de barras errada" — era sobre um render
que o leitor da Fase 6 substituiu; a discordância evaporou junto. **Medição envelhece: re-meça
antes de argumentar com um número antigo.**

### O defeito que era real: o juiz não via TEXTO

`text_match` — a métrica de tinta tolerante a desalinhamento — era calculada, reportada e
tinha **peso zero** no Score. Numa capa cujo texto está todo certo ela lia 0.82 enquanto o
`content_match` lia 0.157.

Ponderar por ÁREA de texto **não** resolve: nessa mesma capa as caixas de texto ocupam 2% da
página e o tipo é o design inteiro. O que entrou (`_content_split`) pondera pela fatia do
**conteúdo**: os pixels de conteúdo dentro das caixas vão para a métrica tolerante, o resto
fica no casamento estrito.

Prova de que não é leniência disfarçada: as capas **sem texto ficaram idênticas ao dígito**, e
o banco de provas seguiu em 4/4.

⚠️ **Todo mundo subiu de nota, e isso não quer dizer que as capas melhoraram** — o número
passou a enxergar algo que antes era invisível. Metas antigas precisam ser relidas na escala nova.

---

## 5. O vocabulário (o que o sistema sabe desenhar)

Tudo é **dado** no `analysis.json`; o renderizador é determinístico.

**Todo primitivo é AUTO-SUFICIENTE: desenha-se a partir dos próprios campos.** Parece óbvio e
não era: o `triangle` só sabia sua orientação através de uma região PARCEIRA, então um
triângulo solto caía num canto chutado. Isso sozinho segurava o leitor inteiro — ele
encontrava os 86 triângulos de um mosaico corretamente e o render saía com metade espelhada.

| primitivo | onde nasceu | observação |
|---|---|---|
| retângulo / grade | capa4 | a base |
| **retângulo arredondado** | capa10 | `radius_cm`; raio = metade do lado curto vira um stadium |
| **elipse** | Fase 6 | o `circle` usava `min(w,h)` e encolhia bbox oblonga em silêncio |
| triângulo | capa4 | carrega `points_cm` (3 vértices) ou `orientation`; o par de meias-células continua como caminho legado |
| **texto rotacionado** | capa14 | `rotation_deg` no elemento de texto |
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

## 8. Estado atual das 20 capas

Números da rodada completa, conferidos pela auditoria (`automation/tools/audit.py`): **20/20
reproduzem o entregável** — o `analysis.json` em disco re-renderiza exatamente o `render.png`
entregue. **Média 0.8529**, **onze capas ≥ 0.90**.

| faixa | capas |
|---|---|
| ≥ 0.90 (onze) | capa4 0.967 · capa12 0.952 · capa6 0.951 · capa11 0.946 · capa8 0.933 · capa9 0.932 · capa13 0.928 · capa19 0.919 · capa16 0.919 · capa7 0.918 · capa20 0.900 |
| 0.80–0.90 | capa5 0.816 · capa1 0.815 (manual) · capa10 0.808 · capa17 0.808 · capa18 0.808 · capa3 0.803 |
| < 0.80 | capa14 0.728 · capa2 0.706 · capa15 0.581 |

**A capa8 é a prova do produto.** Ela entrou FRIA — nunca ajustada, sem nenhum passe de VLM,
em modo puramente determinístico — e marcou **0.933**. É o teste de aceite da promessa "manda
uma capa nova, recebe o PDF", e ele passa. As capas 9, 11, 12, 13, 16 e 20 também estão acima
de 0.90 sem VLM.

**A capa1 continua sendo a única que não fecha ponta a ponta.** O EasyOCR lê o anel dela como
o dígito **"6" a 411pt**. O entregável (0.815) vem de cache manual; automática ela dá 0.736.
`automation/tools/merge_capa1.py` regenera as regiões. **Nunca rode a capa1 em `plain`** — o
`run_batch.py` recusa, porque foi assim que o entregável dela já caiu de 0.796 para 0.603.

**A capa15 (0.581) é a única que nunca se moveu.** 92% do conteúdo dela é texto, as palavras
saem certas e os TAMANHOS errados. É teto medido: o tipo é enorme com entrelinha apertada, os
glifos se tocam e o calibrador não consegue separar uma banda de linha para medir.

---

## 8b. Fase 7 — a cópia recebe o NOSSO conteúdo

Copiar o pôster é metade do produto. A outra metade é: **a mesma capa, com o conteúdo do
livro**. É o que `automation/scripts/cover_integrator.py` faz.

Ele mantém tudo que foi medido — posição, corpo, peso, alinhamento, entrelinha e a **paleta
inteira** — e troca só as strings, pelas de `config/metadata.tex`, mais a marca real de
`brands/<marca>/logos/*.tikz`. As cores da marca **não** entram: a paleta do pôster é o ponto.

**Como os campos caem nos slots.** Linhas vizinhas de mesmo corpo, mesma margem esquerda e
linha de base próxima são agrupadas num BLOCO — senão o título de duas linhas da capa1
("Título do Livro" + "Técnico") viraria título + subtítulo. Os blocos são ranqueados por
corpo e recebem, em ordem, `\BookTitle`, `\BookSubtitle`, `\BookAuthor`, `\BookDescription`,
`\BookSeries`, `\BookVersion`, `\BookDate`, `\BookConfidentiality`. **O que sobra mantém o
texto original da imagem** — decisão do usuário. Medido nas 20: 129 slots recebem conteúdo,
7 mantêm o original.

**Quebra de linha e corpo são escolhidos JUNTOS.** Nossas strings são mais longas que as do
pôster: o slot do título da capa19 tem "theshining" (10 caracteres) e precisa levar "Título do
Livro Técnico" (23). Deixado ao cap de overflow do renderizador, o título encolhe de 103.8pt
para 45.1pt — cabe, e a capa perde a dominância tipográfica que **é** o design suíço. O
integrador faz o que um designer faz: mantém o corpo e quebra a linha, até 3 linhas, exigindo
que o corpo fique em pelo menos 55% do medido. A capa19 fecha em 2 linhas a 76pt.

**Onde vai a marca.** Na bbox medida quando existe (só capa1, capa7 e capa14 têm — o campo
`has_logo` é inerte e mente nos dois sentidos: vem `True` na capa3, que é op-art puro, e
`False` na capa12 e na capa15). Nas outras, a página é cortada numa grade e cada célula
pontuada pela variação da imagem original — mas **desqualificada se encostar numa caixa de
texto NOSSA**: calmo no pôster não é livre na nossa capa. A variante clara/escura sai da
luminância medida atrás do slot.

**Cor por trecho.** Uma linha que atravessa uma borda dura não tem UMA cor boa: para
preto+amarelo o ótimo de contraste é um oliva médio que lê mal nos dois. O integrador divide
a linha onde o fundo muda e dá a cada parte a cor que contrasta com o SEU fundo, encaixando o
corte na fronteira de palavra quando há uma por perto.

**Como entra no livro — a fiação já existia.** `frontmatter/cover.tex` prefere
`\VSBookCoverDynamic`, que renderiza `\RenderDynamicCover`, que é exatamente o que o
`tikz_generator` emite. Escrever o tikz integrado em `styles/versatus-dynamic-cover.tex` basta.

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

## 10b. Como o trabalho anda hoje (o método que funciona)

O usuário olha uma capa e descreve o defeito em português. O dev localiza a causa **no
código**, mede o efeito nas 20 capas, e fecha. Não se escreve regra a partir de uma capa: a
hipótese é medida no conjunto inteiro primeiro, e frequentemente ela morre lá — duas
hipóteses sobre "gráfico lido como texto" foram medidas e ambas saíram **invertidas**.

Cada defeito termina em um de quatro estados: **ABERTO**, **FECHADO** (com o número),
**BLOQUEADO por X** (registra o motivo e libera o próximo) ou **NÃO É CLASSE** (a medição
mostrou que é local, não geral). Os três últimos são conclusões válidas — só ABERTO fica
devendo.

**Ferramentas de apoio:** `automation/tools/run_batch.py` (roda várias capas com progresso
visível em `_run_status.md`) e `scratchpad/audit.py` (confere que o `analysis.json` guardado
ainda reproduz o render entregue — a família de bug mais cara do projeto).

## 10c. A classe de bug que mais custou: REGRA CEGA

Três defeitos independentes, encontrados pela narração do usuário em dias diferentes, acabaram
tendo a mesma forma: **uma regra escrita para resolver UM caso, que passa a apagar coisa
legítima em outras capas, sem medir nada.**

| regra | nasceu para | passou a apagar |
|---|---|---|
| `min(m.shape) < 4` no leitor | rejeitar ruído | **toda régua fina** (design suíço vive delas) |
| `_suppress_text_in_shapes` | o anel da capa1 lido como "6" | **todo texto dentro de círculo** |
| `dedup_text` por vizinhança | remover a leitura que o VLM substituiu | **texto sob a caixa de outro texto** |

E em dois dos três casos **a versão MEDIDA já existia** (`_select_text`: remove, renderiza,
mantém a remoção só se o Score sobe). A regra cega tinha virado redundante e ninguém removeu.

⚠️ A troca foi testada nos DOIS sentidos, e o resultado é honesto: a versão medida recuperou o
que a regra quebrava (capa11 voltou a ter texto) mas **não reproduziu o que ela acertava** — o
"6" da capa1 é testado pelo portão e MANTIDO, porque a métrica o prefere. A regra saiu porque
custava uma capa inteira e não comprava nada mensurável; a máquina certa fica no lugar, inerte,
até o juiz melhorar.

**Varredura:** restam ~19 descartes sem medição no pipeline. `grep -B1 continue` atrás de `if`
com limiar é o jeito de achá-los.

## 11. Como rodar

```bash
# uma capa, determinística
python automation/scripts/replicate_cover.py capas_teste/capa_teste4.png

# com o proponente VLM (usa o cache de edits; não gasta API)
python automation/scripts/replicate_cover.py capas_teste/capa_teste5.png --vlm

# forçar nova chamada ao Gemini (gasta API)
python automation/scripts/replicate_cover.py capas_teste/capa_teste5.png --vlm --vlm-refresh

# painel visual das 20 (o olho como portão) — rápido, sem re-rodar
python automation/scripts/review_board.py

# painel de 3 faixas: original | cópia | cópia com o conteúdo do metadata
python automation/scripts/review_board.py --integrated

# a capa replicada recebendo o conteúdo do livro (Fase 7)
python automation/scripts/cover_integrator.py 19

# rodar várias capas com progresso visível (escreve _run_status.md)
python automation/tools/run_batch.py plain=3,9,10 vlm=1,2,6

# o analysis.json em disco ainda reproduz o render entregue?
python automation/tools/audit.py

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
- **Reconstruir logomarcas.** O sistema **reconhece** e nunca redesenha a marca do pôster.
  O placeholder `"<Nome> (Logo)"` marca a POSIÇÃO, e a Fase 7 usa essa bbox para inserir o
  logo REAL da marca a partir de `brands/` — que é o passo futuro citado aqui, agora feito.
- Mexer em `styles/`, `brands/`, `vision_extractor.py` ou no template do livro — outro fluxo.
- Perseguir SSIM > 0.95 com micro-tuning.

---

## 13. O que vem a seguir

1. **capa15, capa2 e capa14** — as três que o olho reprova. São o mesmo teto: tipografia que
   o calibrador não consegue medir porque os glifos se tocam.
2. **Determinismo da capa1** — o último furo no "manda a imagem → sai o PDF".
3. **`font.identify`** — hoje a fonte cai sempre no substituto cego (TeX Gyre Heros). O
   usuário pediu explicitamente que o sistema **identifique e reporte** qual fonte falta.
   Está planejado e não existe em código.
4. **Largura de texto com métrica real.** A Fase 7 estima ~0.52em por caractere; serve para
   posicionar e quebrar linha, não para justificação fina. O caminho é medir a caixa no
   próprio LuaLaTeX, não refinar a constante.
5. **`judge_bench.py` não existe mais.** O banco de provas do juiz precisa ser reescrito
   antes de qualquer nova tentativa de mexer no Score.
