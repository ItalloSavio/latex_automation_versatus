# Código atual — o que existe, o que faz, onde está o teto

> Retrato do sistema em **2026-09-10**, com números medidos nesta data, não estimados.
> Documento de leitura; as regras de trabalho ficam no `CLAUDE.md` e a explicação didática
> do pipeline no `doc-pipe.md`.

---

## 1. O objetivo

**Entrada:** a imagem de uma capa em design suíço.
**Saída:** um PDF LaTeX/TikZ visualmente idêntico àquela imagem.
**Autonomia:** o sistema mede o próprio resultado e se corrige sozinho até a comparação
máquina-a-máquina considerar original e render iguais.

Duas coisas que **não** são objetivo e é importante estarem escritas: reconstruir logomarcas
(o sistema identifica que há uma marca e nunca a redesenha) e acertar o CONTEÚDO do texto —
o que importa é o tipo parecer com o original em tamanho, peso, alinhamento e entrelinha.

Sobre isso há um segundo bloco, a **Fase 7**: pegar a réplica e trocar o conteúdo pelo do
livro (textos do `config/metadata.tex` e a marca da Versatus). Ele existe e funciona, mas
está separado do replicador e não é o foco atual.

---

## 2. Como o código está organizado

São **12.240 linhas** em `automation/scripts/`, mas nem tudo é do replicador.

### O caminho principal — da imagem ao PDF

```
imagem
  → ocr_extractor.py      (503)  EasyOCR + medição de TINTA: caixa, linha de base,
                                 tamanho, peso e cor de cada texto. Roda PRIMEIRO,
                                 porque as caixas dele alimentam o resto.
  → structural_reader.py  (347)  O LEITOR GENÉRICO. Quantiza na paleta, tira componentes
                                 conexos por cor e escolhe, para cada um, o primitivo que
                                 melhor EXPLICA seus pixels (IoU). Produz 18 das 20 capas.
  → image_analyzer.py    (1808)  CV clássico: paleta k-means, grade por Sobel, diagonais,
                                 círculos por Hough. Hoje só vence o leitor em capa1 e
                                 capa4 — mas também produz a PALETA que o leitor usa.
  → pattern_detector.py   (382)  Repetição e simetria viram \foreach.
  → font_matcher.py       (264)  Família e peso, a partir da espessura de traço medida.
  → cover_assembler.py    (457)  Orquestra a ordem e junta tudo num analysis.json.
  → tikz_generator.py     (857)  JSON → TikZ determinístico. Sem LLM nenhum aqui.
  → replicate_cover.py    (929)  LuaLaTeX ×2 → PDF → PNG → compara → LOOP de correção.
  → visual_comparator.py  (756)  As métricas, o mapa de diferença e as manchas de resíduo.
  → calibrator.py         (311)  Mede a tinta do render contra a do original e corrige
                                 tamanho e posição elemento a elemento.
```

### O VLM, que é proponente e não protagonista

```
  vlm_proposer.py  (267)  Manda imagem + render + análise ao Gemini e recebe EDITS TIPADOS.
  edit_gate.py     (941)  O porteiro anti-alucinação, em duas camadas: aterramento barato
                          (a cor existe na paleta? a posição cabe na página?) e depois o
                          portão MEDIDO, um edit por vez — aplica, renderiza, mede, e só
                          mantém se melhorou.
```

O invariante que segura tudo: **o VLM emite DADO, nunca CÓDIGO**. O `analysis.json` cresce
sozinho; o vocabulário de primitivos só cresce com o dev, sob portão de regressão.

### Fase 7 — a réplica recebendo o nosso conteúdo

`cover_integrator.py` (1809) mantém a arte replicada como fundo e coloca por cima os textos
do metadata e a marca. Funciona, está entregue em `Layout/`, e **não é o foco agora**.

### Ferramentas de diagnóstico (`automation/tools/`, 422 linhas)

| ferramenta | para quê |
|---|---|
| `audit.py` | o `analysis.json` em disco ainda reproduz o `render.png` entregue? |
| `run_batch.py` | roda várias capas com progresso visível |
| `render_analysis.py` | renderiza e mede qualquer análise com a máquina real |
| `diff_blobs.py` | manchas de discordância ranqueadas — acha a causa sem chutar |
| `vectorize.py` | o vetorizador rejeitado, guardado como rede de segurança |
| `merge_capa1.py` | necessário para regenerar a capa1, que renderiza de cache |

### O que NÃO é do replicador

`vision_extractor.py`, `build_cover.py`, `svg_to_tikz.py`, `convert_logos.py` e
`preview_cover.py` pertencem ao fluxo do livro-template. Os dois últimos ainda são úteis
porque **geram os logos TikZ** que a Fase 7 consome.

---

## 3. Tecnologias

| camada | o que é usado | versão aqui |
|---|---|---|
| OCR | EasyOCR (CPU, sem CUDA) | 1.7.2 |
| Visão / CV | OpenCV, scikit-learn (k-means), SciPy (componentes, watershed) | 5.0.0 / 1.9.0 / 1.18.0 |
| Numérico / imagem | NumPy, Pillow | 2.5.1 / 12.3.0 |
| Renderização | LuaHBTeX + TikZ (MiKTeX) | 1.24.0 |
| PDF → raster | PyMuPDF | 1.28.0 |
| VLM | google-genai (Gemini, cadeia flash → 2.0) | 2.10.0 |
| Fonte | Helvetica → **TeX Gyre Heros** → Arial | clone métrico |

A fonte é o único ponto onde há substituição assumida: a real é paga, então todo o tipo sai
num clone métrico. As letras batem de largura, mas não são o mesmo desenho.

---

## 4. As métricas

O que o loop otimiza:

```
score = 0.30 · SSIM  +  0.50 · content_effective  +  0.20 · content_iou
```

| métrica | o que mede |
|---|---|
| `ssim_global` | similaridade estrutural, ponderada por ÁREA |
| `content_effective` | o termo de conteúdo: TIPO pelo `text_match` tolerante, o RESTO pelo casamento estrito, misturados pela fatia de cada parte no conteúdo |
| `content_match` | qualidade só nos pixels que não são fundo |
| `content_iou` | sobreposição das máscaras de conteúdo |
| `text_match` | F1 da tinta dentro das caixas de OCR, tolerante a desalinhamento |

### ⚠️ Três avisos sobre confiar nesses números

**O Score não separa as classes do olho.** Medido sobre 123 pares: as capas que o usuário
chamou de BOAS iam de 0.581 a 0.968 e as PÉSSIMAS de 0.615 a 0.802 — sobreposição quase
total. **Priorizar pelo número leva a trabalhar na capa errada.**

**SSIM sozinho engana** porque é ponderado por área: uma capa 75% preta ganha SSIM alto só
acertando o fundo.

**Uma métrica pode ser bom RANKEADOR e péssimo ALVO.** Já trocamos o Score por um que
ordenava melhor (82.9% de concordância contra 71.5%) e ele apagou texto de quatro capas,
porque nem SSIM nem casamento de formas percebem texto FALTANDO. Foi revertido no mesmo dia.

---

## 5. Onde o sistema está hoje

**As 10 capas do MVP** (escolha do usuário): média **0.9026**.

| capa | Score | | capa | Score |
|---|---|---|---|---|
| capa4 | 0.9665 | | capa13 | 0.9277 |
| capa12 | 0.9559 | | capa7 | 0.9184 |
| capa6 | 0.9531 | | capa16 | 0.9177 |
| capa8 | 0.9356 | | capa19 | 0.8878 |
| | | | capa1 | 0.8195 |
| | | | capa2 | 0.7438 |

**As 20:** média 0.8605, **10 acima de 0.90**. A pior é a capa15 (0.5812), a única que nunca
se moveu.

**A prova de que generaliza:** a capa8 entrou fria — nunca ajustada, sem passe de VLM, modo
puramente determinístico — e marcou 0.93. É o teste de aceite do produto "manda uma capa
nova, recebe o PDF".

**Uma leitura de cuidado:** a capa2 tem 0.7438 e o usuário a classificou como BOA. Ela é 98%
fundo claro com tipografia fina, e o Score é duro com texto fino. O número lá mente para
baixo.

---

## 6. Onde está o erro — medido, não suposto

Decompus a discordância de pixels das 10 capas do MVP em classes que apontam para consertos
diferentes:

| classe | peso | o que é |
|---|---|---|
| **borda** | **63%** | nossas formas 1–2px fora do lugar |
| **cor** | 15% | ambos têm conteúdo, cores diferentes |
| **faltando** | 12% | o original tem conteúdo, nós não |
| **sobrando** | 10% | nós desenhamos, o original não tem |

Três coisas que essa medição revelou:

**A paleta está travada em 8 cores.** `_N_COLORS = 8` é constante fixa. A capa16 usa ~15
cores significativas, capa4 e capa12 ~13. O sinal de que isso dói: **a menor cor da paleta
da capa4 cobre 5,37% da página** — uma cor com 5% de área sendo a *menor* que guardamos
significa que o k-means ficou sem clusters e está fundindo cores de design. Quantizando o
próprio original em k=16, o erro de cor cai **62% na capa4, 52% na capa12, 44% na capa7**.

**Os 63% de borda NÃO são resolução — isso foi testado.** Renderizei a 450dpi em vez de 150
e o saldo foi +0.0016 em cinco capas: ruído. Não é anti-serrilhado do rasterizador, é
desalinhamento geométrico. O contorno é traçado sobre uma máscara limiarizada, que já perde
meio pixel na borda.

**Os 10% "sobrando" não são fantasmas.** A suspeita era de círculos alucinados pelo Hough.
Com uma abertura morfológica separando mancha real de franja, a capa7 não deixou **nada**
relevante e a maior mancha da capa1 é 0,03% da página. É franja de anti-serrilhado contada
como erro. **Não há trabalho a fazer aí** — e saber disso economiza mais que consertar.

---

## 7. O que falta

### Endereçável, com ganho medido

**Paleta adaptativa.** Trocar o `k` fixo por um derivado de quantas cores a imagem realmente
tem. É uma constante, o ganho está medido em 7 das 10 capas, e o portão de regressão das dez
protege a capa4.

**Contorno sub-pixel.** Ajustar o traçado à borda anti-serrilhada em vez da máscara binária.
É trabalho maior, mas é o único caminho para os 63% e é o que separa "quase igual" de
"igual".

### Fila aberta, sem ganho garantido

| item | estado |
|---|---|
| capa10 lê o gráfico como texto ("UUU" a 351pt) | bloqueado pelo juiz: remover baixa o Score |
| capa15 e capa14, tipografia | teto medido — glifos se tocam, o calibrador não consegue medir |
| capa10, barras em U | precisa de regra composicional que não existe |
| capa1 depende de cache manual | resolvível: o leitor automático já dá 0.8567 |
| 11 capas nunca viram o VLM | custa API |
| `judge_bench.py` não existe mais | precisa ser reescrito antes de mexer no Score |

---

## 8. Estamos no teto?

**Do jeito atual, quase.** E dá para separar o que é teto de verdade do que é limite de
implementação:

**Teto real, não removível sem mudar premissa:**
- A **fonte** é um clone métrico. A real é paga. Todo o tipo herda isso.
- **Vetor rasterizado contra foto** trava o SSIM perto de 0.95 mesmo quando o olho não
  distingue.
- Tipografia com **glifos que se tocam** (capa15, capa14) não é mensurável pelo calibrador.

**Limite de implementação, ainda removível:**
- A **paleta de 8 cores** — com headroom medido de 28% a 62%.
- O **contorno limiarizado**, que custa meio pixel em toda borda — 63% do erro restante.

**A resposta honesta:** as dez do MVP estão em 0.9026 e o que sobra é 63% de borda, que é
implementação, não física. Ainda há caminho — mas o próximo passo custa mais que todos os
anteriores, porque os ganhos baratos já foram tomados.

E há um limite que nenhum número resolve: **o Score não separa as classes do olho.** Enquanto
isso for verdade, o juiz final continua sendo você olhando o `MVP/comparacao/`.
