# pipeline-ideal — o desenho que o projeto está pedindo

> Escrito em **2026-09-14**, depois de uma pergunta que expôs o problema melhor do que eu
> tinha conseguido: *"o hill-climbing está sendo usado da maneira mais eficiente?"*
>
> Não é uma reescrita. É o mesmo pipeline com **uma** mudança estrutural e cinco ajustes,
> todos apoiados em medição desta sessão. O que está `MEDIDO` tem número; o que está
> `PROJETO` é desenho e ainda não foi provado.

---

## 1 · O diagnóstico, em uma frase

**O laço itera sobre as variáveis que o juiz não enxerga, e não itera sobre as que ele
enxerga.**

`MEDIDO` — o espaço de busca inteiro do hill-climbing são dois proponentes:

| proponente | o que ele escreve |
|---|---|
| `calibrator.calibrate()` | `font_size_pt`, `hscale`, `dx_cm`, `dy_cm` |
| `_apply_patches()` | a cor de uma região |

Métrica de tipografia e cor de área. Ele **não** pode mover forma, trocar primitivo, corrigir
string, nem acrescentar ou remover peça. Toda a geometria é decidida **uma vez** no estágio 7
e o laço nunca volta lá.

E o juiz é o Score, que é quase cego a tipografia — quatro evidências independentes só nesta
semana: apagar o `"the"` da capa19 **subiu** 0.055; apagar `'the velvet'` subiu 0.003; corrigir
a cor de 68 elementos moveu **±0.0002**; e remover o `"6"` falso da capa1 **custa 0.13**.

Daí o resultado concreto: a capa13, com dois passes de calibração, ganha **+0.0023**. Não é o
calibrador que é fraco — é que ele é avaliado pelo instrumento errado.

---

## 2 · Três máquinas fazendo a mesma coisa

O padrão *"propõe → renderiza → mede → fica se melhorou"* está implementado **três vezes**,
com juízes diferentes e espaços de busca diferentes:

| onde | quem propõe | juiz | quando roda |
|---|---|---|---|
| estágio 7 | leitor vs detectores, camadas, texto | Score | uma vez |
| estágios 8–11 | calibrador, patch de cor | Score | em laço |
| estágio 13 | VLM | Score **e** `text_match` e `box_local`, roteados | no platô |

O estágio 13 é o único que **roteia a métrica por tipo de edit** — e não por acaso é o que
mais rende. A Fase E deu +0.0672 na capa19 e corrigiu o texto da capa16, coisas que o laço
determinístico jamais alcançaria.

**A mudança estrutural é unificar as três num laço só, com um registro de proponentes e um
portão que roteia a métrica.** Não é abstração por elegância: é dar ao laço acesso ao espaço
de busca que o juiz consegue avaliar.

---

## 3 · O pipeline ideal

```
imagem
  │
  ├─ LEITURA (uma vez)
  │    ocr_extractor      texto + tinta medida          ─┐
  │    palette            a paleta k-means               ├─► estado inicial
  │    structural_reader  componentes → primitivos      ─┘
  │    ⚠ detectores (image_analyzer) só sob DEMANDA — ver §4.4
  │
  ├─ REFERÊNCIA  ◄── novo, e é o que destrava o resto
  │    guarda o que o OCR leu ANTES de qualquer seleção.
  │    Sem isso não existe a pergunta "esta linha sumiu?".
  │
  ▼
┌─ LAÇO ÚNICO ──────────────────────────────────────────────────────────┐
│                                                                        │
│  REGISTRO DE PROPONENTES        cada um devolve EDITS TIPADOS          │
│    · reader-variants  (drop_films, piso de área, split)                │
│    · detectores       (quando o leitor não explica)                    │
│    · layer-drop       (a camada se paga?)                              │
│    · text-drop/retrace                                                 │
│    · calibrator       (métrica de tipo)                                │
│    · colour-patch                                                      │
│    · VLM              (string, peso, forma nova)                       │
│                                                                        │
│  PORTÃO ÚNICO                                                          │
│    1. aterramento   cor ∈ paleta? cabe na página? primitivo existe?   │
│    2. VETO          o edit cria defeito estrutural? → rejeita direto   │
│    3. métrica ROTEADA pelo tipo do edit:                               │
│         geometria/região  → Score                                      │
│         métrica de texto  → text_match na CAIXA que mudou              │
│         presença de texto → diff contra a REFERÊNCIA                   │
│    4. aceita e guarda · ou reverte                                     │
│                                                                        │
│  PARA QUANDO   o veredito estrutural é OK  ·  nenhum proponente tem    │
│                proposta  ·  orçamento esgotado                         │
└────────────────────────────────────────────────────────────────────────┘
  │
  ▼  analysis.json · cover.tikz · cover.pdf · veredito
  │
  └─ CONTEÚDO (opcional, --integrar) ──► cover_integrator + cache de arte
```

---

## 4 · As mudanças, uma a uma

### 4.1 · Rotear a métrica dentro do laço  `pequeno` · **o maior retorno por esforço**

O `edit_gate` já faz isso; o laço não. Um edit do calibrador muda **uma caixa de texto** e é
julgado pelo Score **global** — uma página inteira de pixels para avaliar uma linha.

`MEDIDO` — é por isso que 68 correções de cor de tinta moveram ±0.0002 e a decisão teve de ser
do olho. Com roteamento, cada correção é julgada por `text_match` **na caixa que ela mudou**,
que é a medida que reage.

**O mecanismo já existe e está testado em outro arquivo.** É ligar, não construir.

### 4.2 · Defeito estrutural como VETO, não como peso  `médio`

O `accept.py` existe e discrimina: diz `REVISAR` na capa1 automática (pegando o `"6"` a 411pt)
e `OK` na manual. Mas ele roda **depois de tudo** e não guia nada.

Trazê-lo para dentro do portão. E a forma importa: **veto, não termo ponderado.**

`MEDIDO` — a história diz por quê. Em 18/08 o `text_match` virou peso no Score e em 19/08 foi
tirado; uma troca de pesos que ordenava melhor (82,9% contra 71,5%) **apagou texto de quatro
capas**. Assim que um defeito vira número, ele vira negociável — e o laço negocia. Um título
ausente não vale 0.05 de SSIM; ele simplesmente não pode passar.

### 4.3 · A REFERÊNCIA — e uma falha do meu próprio portão  `pequeno` · **pré-requisito do 4.2**

`MEDIDO` — testei o `accept.py` contra a capa19 que perdeu o `"the"`: ele responde **`OK`**.
Ele detecta tipo grande demais, vazamento, sobreposição e letra virada mancha — mas **não
detecta ausência**, porque só olha a análise final. Sem saber o que havia, não há como saber
o que sumiu.

O pipeline **tem** essa informação e a descarta: a lista do OCR antes do `_select_text`.
Guardá-la como `reference.json` custa uma linha e torna possível a única pergunta que pegaria
os quatro defeitos da §1: *"toda linha que o OCR leu com confiança alta tem correspondente no
entregável?"*

### 4.4 · Detectores sob demanda  `pequeno`

`MEDIDO`, com warm-up:

```
paleta sozinha          : 0.94 s
image_analyzer COMPLETO : 1.81 s     ← detectores = 0.88 s
structural_reader       : 0.34 s
```

Os detectores custam **0.88 s por capa e são descartados em 8 de 9**. Toda capa paga grade por
Sobel, círculos por Hough e passes de diagonal cujo resultado o portão joga fora.

⚠️ **Não é ganho grátis.** O portão só sabe que os detectores perdem **depois** de medir. O
critério honesto: rodar paleta + leitor primeiro e invocar os detectores só quando o leitor
fica abaixo da meta. Na capa4 — a única que os usa — o leitor dá 0.9654 contra 0.9665: um
limiar razoável a dispensaria e custaria **0.0007**. É uma troca, e o número dela está aqui.

### 4.5 · `max_passes` de volta a 3  `trivial`

`MEDIDO` — o `cover_pipeline.py` que escrevi tem `max_passes=1`, e o laço quebra em
`if _pass == max_passes` **antes** do estágio 12. Resultado: **zero elementos calibrados nas 9
capas**. A máquina esteve inerte no MVP inteiro.

⚠️ Sozinho, isso é iteração no lugar errado (§1). Faz sentido **depois** do 4.1.

### 4.6 · Uma regra só para cache  `pequeno`

Hoje há três caches com semânticas diferentes, e um deles **foi um bug** — o `vlm_analysis.json`
era lido de volta como resposta pronta e congelou nove capas. A regra que sobreviveu:

> **Cache guarda PROPOSTA, nunca RESPOSTA.** Toda proposta é re-julgada pelo portão da rodada
> atual.

`MEDIDO` — o cache de arte violou isso de outro jeito e eu repeti o erro: comparava contra o
**número guardado**, então quando a penalidade ganhou um termo, toda entrada velha virou
incomparavelmente boa. Corrigido re-medindo o cache com o juiz de hoje.

---

---

## 4.7 · O PASSE DE REFINAMENTO — separado do pipeline, de propósito

> Desenho do usuário (14/09), e é melhor que a alternativa que eu tinha proposto.

**A ideia:** depois que a capa está construída, um processo **separado** abre a imagem original
ao lado da última capa buildada, identifica **onde o sistema decidiu errado**, entende isso
como erro, revisa e tenta melhorar. Exemplo concreto: o sistema recusou um texto porque não
viu texto ali — e claramente há texto. Isso é um **erro de decisão**, não um desvio de pixel.

### Por que FORA do pipeline, e não dentro

Três razões, todas medidas:

**1 · O detector de resíduo de dentro do laço é cego a texto fino POR CONSTRUÇÃO.** Ele usa
abertura morfológica para separar mancha real de franja de anti-serrilhado, e essa operação
apaga tipografia miúda. Está no próprio código: *"o resíduo GUIA, nunca BARRA"* — numa capa
dominada por texto ele devolve zero manchas, e a capa2 perdeu toda a contribuição do VLM assim
(0.3457 → 0.3352). **O mecanismo que deveria dizer "falta texto aqui" é o que não vê texto.**

**2 · Um VLM comparando DUAS IMAGENS não tem essa cegueira.** Ele olha original e render e diz
*"nesta posição há uma linha de texto que você não desenhou"*. É um sinal que nenhuma métrica
de pixel do pipeline produz, e não depende do estado interno do pipeline — só dos dois PNGs.

**3 · Cada peça que entrou no laço nesta semana criou regressão em outro lugar.** O retraço
converteu texto bom em arte. Os buracos abriram uma barra preta na capa8. O `half_ellipse`
quebrou a penalidade de layout. Um passe separado **pode errar sem contaminar a cópia**.

### O padrão já existe no projeto

`cover_integrator.build_refined()` faz exatamente isto para o LAYOUT: integra, deixa o VLM
criticar a página pronta, aplica cada proposta pelo portão, cacheia as propostas. **Falta o
equivalente para a RÉPLICA.** Não é arquitetura nova — é o mesmo padrão num segundo alvo.

### Desenho

```
capa construída (render.png)  +  imagem original
          │
          ▼
   VLM: "compare. O que EU errei?"          ← o enquadramento é o ponto:
          │                                   não "melhore", e sim "onde decidi errado"
          ▼
   edits TIPADOS (o vocabulário de hoje: text.add, text.string, region.*)
          │
          ▼
   PORTÃO existente: aterramento → métrica roteada → aceita ou reverte
          │
          ▼
   repete até: nada landa · pendências resolvidas ou BLOQUEADAS com medição · orçamento
```

**Entrada:** os dois PNGs + o `analysis.json` (para poder emitir edit).
**NÃO re-roda** OCR nem CV. Trabalha sobre o artefato pronto.
**Saída:** análise revisada + o registro do que foi corrigido e do que ficou bloqueado.

### O que ele precisa e não existe

- **Um prompt orientado a ERRO**, não a melhoria. Hoje o `vlm_proposer` pede "proponha
  correções"; aqui a pergunta é *"o que o sistema deixou de ver?"*.
- **Estado de pendência**: cada erro identificado vive como `aberto → resolvido → bloqueado
  (com a medição que provou o teto)`. Sem isso o passe repropõe o mesmo erro toda rodada — foi
  o que aconteceu com o dedup de `text.add`, que precisou de guarda justamente por isso.

---

## 5 · O que NÃO muda

Vale dizer, porque a tentação de reescrever é grande e estas peças estão certas:

- **OCR antes de CV.** As caixas de texto alimentam o mapa de layout; inverter fez texto grande
  virar linha de grade falsa.
- **O VLM emite DADO, nunca CÓDIGO.** É o que contém alucinação. O vocabulário-código só cresce
  com o dev, sob portão de regressão.
- **Portão medido em vez de confiança do detector.** É a arquitetura central e ela funciona: na
  Fase E o VLM propôs 12 edits na capa4 e o portão rejeitou **todos**.
- **O olho como desempate.** Metade das decisões boas desta semana vieram de olhar, não de
  medir — o título da capa8, a cor da tinta, a capa19 revertida.

---

## 6 · Ordem de implementação

```
1. REFERÊNCIA (4.3)           ✅ 16/09 — make_reference.py + reference.json no assembler
2. Roteamento de métrica (4.1) ✅ 17/09 — replicate_cover._correct (tipo por caixa, cor por Score)
3. Defeito como veto (4.2)     🔶 no PORTÃO de aceite e no refinamento; NÃO dentro do laço
4. max_passes = 3 (4.5)        ✅ 17/09 — cover_pipeline e run_batch
5. Registro de proponentes     ⏸ ainda não — ver abaixo
6. Detectores sob demanda (4.4) ⏸ independente
   Passe de refinamento (4.7)  ✅ 17/09 — refine_replica.py, opt-in, fora do pipeline
```

⚠️ **O que a implementação de 17/09 ensinou sobre este desenho, medido:**
- O §4.1 estava certo e o ganho foi maior do que o previsto: o laço antigo julgava calibração e
  patch de cor **juntos** — um A/B confundido por construção. Nas 9 capas ele jogava fora 21
  calibrações que melhoravam a própria linha e aceitava 6 que a pioravam.
- Mas julgar tipo **caixa a caixa** tem um ponto cego que o desenho não previa: janelas de
  linhas vizinhas se sobrepõem, e uma linha pode "melhorar na própria caixa" crescendo por cima
  da vizinha. Apareceu duas vezes no mesmo dia. Em tipo de display o `accept.word_collisions`
  pega; em tipo miúdo está abaixo da resolução das imagens-fonte.
- Dois bugs antigos só apareceram porque o laço passou a ser medido linha a linha: o
  calibrador assumia `hscale` padrão 1.0 enquanto o gerador desenha a 0.89 (toda correção de
  largura virava +12%), e o snap de `text.add` tinha teto de 15pt (nenhum título podia voltar).

⚠️ **Antes de 2 e 3, reescrever o `judge_bench.py`** (item A2 do `pos-mvp.md`). Ele não existe,
e mexer no juiz sem banco de provas já quebrou quatro capas uma vez. Os quatro defeitos da §1
são casos-teste prontos: cada um é um par onde Score e olho discordam, com veredito conhecido.

---

## 7 · O que este desenho NÃO resolve

Honestidade sobre o teto, para ninguém esperar demais:

- **A fonte é um clone métrico.** A real é paga. Todo o tipo herda isso.
- **As imagens-fonte são miniaturas** (0,3–0,8 MP). O comparador reduz o render ao tamanho do
  original antes de medir, então precisão geométrica abaixo do pixel da fonte é inalcançável
  por construção — e foi isso que fez o contorno sub-pixel render só +0.002.
- **O OCR erra caracteres em qualquer escala.** `"bullalo; ncw york"` sobrevive ao upscale 3×.
  Só o VLM corrige, e isso custa API.
- **Gradiente não está no vocabulário** (§B1 do `pos-mvp.md`) — nenhum ajuste de laço inventa
  um primitivo que não existe.
- **Composição "A por cima de B"** continua ausente, e é o que trava a ponta da capa19 e as
  barras em U da capa10.

O laço ideal encontra o melhor ponto **dentro** do vocabulário. Ele não inventa vocabulário.
Essa continua sendo a divisão de trabalho com o dev.
