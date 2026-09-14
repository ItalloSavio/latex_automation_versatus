# pos-mvp — o que fazer depois do MVP

> Escrito em **2026-09-14**, no fechamento do MVP de 9 capas.
> Cada item traz **a evidência medida** que o motiva, não a intuição. Onde um número aparece,
> ele saiu de uma rodada real — e onde uma hipótese morreu na medição, isso está registrado,
> porque saber o que **não** fazer vale tanto quanto a fila.
>
> Estado na entrega: 9 capas, média **0.9003**, auditoria **9/9**, portão de aceite **8/9 OK**,
> penalidade de layout **0.0006**, e **8 das 9** saindo de um comando a partir do PNG.

---

## Como ler esta fila

O projeto tem uma regra que se pagou várias vezes: **medir antes de construir, e re-medir
antes de argumentar**. Quase todo item abaixo já tem medição — o que falta é a construção.
Três itens são explicitamente **hipóteses mortas**, listadas para ninguém gastar tempo nelas
de novo.

Tamanhos são relativos ao esforço do MVP: `pequeno` = uma sessão, `médio` = alguns dias,
`grande` = mudança de premissa.

---

## A · O juiz — a causa-raiz de quase tudo

### A1 · Um Score que enxergue texto AUSENTE  `grande` · **o item mais importante**

**O problema, com quatro evidências independentes:**

| o que aconteceu | o que o Score fez |
|---|---|
| capa19 perdeu o `"the"` de um título de 135pt | **subiu** 0.8368 → 0.8923 |
| capa8 teve `'the velvet'` apagado e ficou um buraco | subiu 0.9280 → 0.9311 |
| capa1 mantém um `"6"` de 411pt que é o anel lido como dígito | remover **custa 0.13** |
| capa8 ganhou uma barra preta atrás das legendas | não reagiu |

Em todos, o número disse "melhorou". A razão é estrutural: o Score é
`0.30·SSIM + 0.50·content_effective + 0.20·content_iou`, e **apagar meio título de 135pt custa
menos que desenhá-lo mal**. Some-se que `text_match` concorda com a classificação visual do
usuário em **51,2%** — acaso puro.

**Por que isso importa mais que qualquer outro item:** o `_select_text` é um portão MEDIDO, e
portões medidos são a arquitetura central do projeto (`_select_layers`, `_select_reader`,
`edit_gate` — todos funcionam). Ele só falha porque o juiz que ele consulta é cego a texto.
Consertar o juiz conserta o portão, destrava a capa1 e remove a necessidade do remendo externo.

**O que existe hoje como paliativo:** `automation/tools/accept.py` cobre o buraco **por fora** —
ele detecta os defeitos depois do fato. Funciona, mas é um alarme, não um juiz: não pode guiar
o loop de otimização, só reprovar o resultado.

⚠️ **O histórico avisa:** em 18/08 o `text_match` foi posto no Score e tirado em 19/08, e uma
troca de pesos (`ssim 0.75 / structural 0.25`) ordenava melhor e **apagou texto de quatro
capas**. Qualquer juiz novo precisa de **dois termos**: algo que ordene como o olho
(`ssim`/`structural`) **e** algo que puna conteúdo AUSENTE. Só o primeiro degenera.

### A2 · Reescrever o `judge_bench.py`  `pequeno` · **pré-requisito do A1**

Não existe. O banco de provas que validava o juiz contra os vereditos já dados pelo usuário
foi perdido, e o `CLAUDE.md` registra isso como pendência desde 09/09. **Mexer no Score sem
ele é como o projeto já errou uma vez**, em 19/08: a troca passou nos dois testes que existiam
e quebrou quatro capas que ninguém testou.

Hoje há material novo para o banco: os quatro defeitos da tabela A1 são casos-teste perfeitos —
cada um é um par onde o Score e o olho discordam, com o veredito humano já conhecido.

---

## B · Vocabulário que falta

### B1 · Gradiente como primitivo  `médio` · **descoberto no teste frio de 14/09**

O teste de aceitação a frio (imagem inédita, comando único) deu **0.9323** e a geometria saiu
excelente — todos os círculos no lugar, tamanho e cor certos. Mas **o fundo em degradê virou
manchas**: a paleta de 8 cores quantiza um gradiente em placas de cor chapada.

**Motivação:** não é um defeito daquela capa, é uma classe. Atinge **qualquer** pôster com
degradê, e degradê é comum em design suíço tardio. Como o sistema hoje promete "manda uma capa
qualquer", este é o buraco mais provável de alguém encontrar sozinho.

**Direção:** um primitivo `linear_gradient` (dois pontos + duas cores) que o leitor proponha
quando uma região tem variação monotônica forte num eixo. TikZ desenha isso nativamente
(`shading=axis`). ⚠️ Passa pelo portão medido como qualquer peça nova, e **ao lado** do caminho
atual, nunca no lugar — a regra que o `_angular_bands` ensinou.

### B2 · Regra COMPOSICIONAL "A por cima de B"  `grande` · defeito D4

Nenhum primitivo diz *"esta peça está POR CIMA daquela"*. A capa10 tem uma barra laranja em U
que nenhuma forma descreve; medido, o núcleo vermelho corre 690 dos 700px, então **não é um
anel** — é um U aberto, e por isso preencher oclusão nunca funcionou lá.

**O que mudou a favor:** os **buracos no traçado** entraram em 11/09 (`RETR_CCOMP` + regra
par-ímpar). Uma forma com cavidade finalmente é exprimível. Isso era o pré-requisito que
faltava; a regra composicional agora tem onde se apoiar.

**Direção registrada:** quando o bbox da peça A contém B inteira e A é mal explicada, testar
`A ∪ B` como um primitivo com B pintada por cima.

---

## C · Leitura

### C1 · Recall de texto — o upscale de OCR, destravado  `médio`

**Medido e REPROVADO em 11/09, mas por razões que são todas consertáveis.** Rodar a detecção
num upscale Lanczos 3× (medindo a tinta na resolução nativa) recupera texto de verdade:

- capa16: 8 → 9 elementos, `'saturday'` e `'7 pm sharp'` recuperadas inteiras, `'only $6 / all
  ages'` e `'october 21 1989'` completadas
- capa8: finalmente **LÊ** `'the velvet'`, hoje desenhado como manchas

Mesmo assim piorou o entregável (0.9386 → 0.9279), por **três causas downstream**:

1. os extras chegam **fragmentados** (`/11`, `pm`, `& 1 am` em três caixas que colidem);
2. a quad mais frouxa faz `_measure_ink` pegar mais que o glifo — legendas a 18,5pt contra
   14,6pt medidos;
3. o texto recuperado era **apagado** pelo portão de texto (item A1).

**Motivação:** o bloco de tipo vazio é o que o olho vê primeiro, e este é o único caminho
barato para preenchê-lo. Resolvido o A1 e a re-união de fragmentos, ele passa a render.

⚠️ **Escala fixa 3× lê melhor que a fórmula adaptativa** que escrevi (ela escolhia 2× na capa8,
e foi isso que fragmentou). Começar por 3×.

### C2 · `font.identify` — identificar e REPORTAR a fonte  `médio`

Hoje toda tipografia cai no substituto cego (TeX Gyre Heros). O usuário pediu explicitamente
que o sistema **identifique e reporte** qual fonte falta. Plano já aprovado e nunca construído:
o VLM classifica família/peso/largura, o gate testa (`text_match` mede), mantém se melhor.

⚠️ **Identificar ≠ ter o arquivo.** Só há ganho real se a fonte estiver instalada; senão o
valor é o **relatório** — "esta capa pede Akzidenz-Grotesk" — que é informação acionável para
quem vai licenciar.

---

## D · Escala e robustez

### D1 · Memória do quantizador  `pequeno` · **bloqueia pôster em resolução real**

`((a[:,:,None,:] - pal)**2).sum(3)` materializa `h × w × k × 3` em float32 de uma vez:

| imagem | k=8 | k=16 |
|---|---|---|
| capa16 (467×657) | 0,03 GB | 0,06 GB |
| capa11 (1200×1680) | 0,19 GB | 0,39 GB |
| **pôster real 12 MP** | **1,15 GB** | **2,30 GB** |

**Motivação:** as imagens do corpus são miniaturas, então isso nunca apareceu. Um pôster de
verdade estoura antes de desenhar o primeiro polígono — e "manda uma capa qualquer" implica
resolução qualquer. Conserto: quantizar em blocos de linhas. Meia hora de trabalho.

### D2 · A resolução das imagens-fonte é o teto de precisão  `grande` · premissa, não bug

As fontes são miniaturas: **0,3 a 0,8 MP** (capa16 é 467×657; a capa3, fora do MVP, tem
**98×96**). E o comparador **redimensiona o render para o tamanho do original** antes de medir.

**Duas consequências que já enganaram o projeto:**
- subir o dpi do render **não pode** mover a métrica, por construção. O teste que "provou que
  os 63% de borda não são resolução" era incapaz de mostrar outra coisa;
- o contorno sub-pixel rende pouco porque meio pixel a 467px é, literalmente, sub-pixel.
  Medido: **+0.0021** de média, e **−0.0088** líquido quando se inclui o dano em componentes
  pequenos.

**Motivação para registrar:** se algum dia houver acesso às imagens em resolução alta, vários
tetos se movem de uma vez — e nenhuma engenharia no código atual os move.

---

## E · Integração e ferramental

### E1 · Provar a capa DENTRO do livro  `pequeno` · **o único elo nunca demonstrado**

A fiação existe: `frontmatter/cover.tex` prefere `\VSBookCoverDynamic`, que renderiza
`\RenderDynamicCover` — exatamente o comando que o `tikz_generator` emite. Mas
`styles/versatus-dynamic-cover.tex` contém hoje uma capa da marca **Kosen**, gerada pelo
`vision_extractor` (outro fluxo). **Ninguém compilou o `main.pdf` com uma das nove dentro.**

**Motivação:** para um MVP cujo propósito é capa de livro, este é o único elo da cadeia sem
prova. É rápido, mas exige backup: sobrescreve a capa Kosen, e `styles/` está marcado como
fora de escopo do replicador.

### E2 · `run_batch.py` fala de 20 capas  `pequeno`

Ainda assume o corpus antigo e recusa a capa1 em `plain` por um motivo que **mudou**: a
proteção existia porque "o OCR dela é não-determinístico", e isso foi **medido em 11/09 e é
falso** (duas rodadas devolvem saída idêntica, até a cor). A proteção continua certa — a capa1
tem cirurgia manual — mas pelo motivo correto.

### E3 · Arquivos de outro fluxo na raiz de `automation/output/`  `pequeno`

`ca_test3.json`, `canvas_last.*`, `test3_cover.tikz` são artefatos versionados do
`vision_extractor`. Não foram removidos na limpeza porque pertencem a outro fluxo e apagar o
que não se mediu é exatamente o erro que este projeto já cometeu. Alguém que conheça aquele
fluxo deveria decidir.

---

## F · Dívida técnica com dono conhecido

| item | evidência | tamanho |
|---|---|---|
| `_TEXT_ADD_SCORE_TOL = 0.02` está frouxo | Foi calibrado quando o Score era cego a texto ("cai ~0.005 mesmo em texto bem posto"). Depois do `_content_split` ele **não é mais cego**, e a folga nunca foi reapertada | pequeno |
| ~19 descartes sem medição no pipeline | Três já cobraram caro (`min(m.shape)<4` comia toda régua fina; `_suppress_text_in_shapes` comia texto em círculo; `dedup_text` comia texto por vizinhança). Restam guards em `ocr_extractor` (`h_box_cm < 0.15`) e nos de círculo do `image_analyzer`. Padrão de busca: `grep -B1 continue` atrás de `if` com limiar | médio |
| `line join=miter` em contorno traçado | Os traçados têm esporas degeneradas: na capa8, **18 de 472 vértices (3,8%) abaixo de 5°**. Com 2pt e o miter limit padrão do PDF, a espícula chega a **10pt = 3,5mm**. `line join=round` é uma linha, mas passa pelo portão de regressão | pequeno |
| `image_analyzer` serve 2 capas de 20 | 1.802 linhas para capa1 e capa4. A paleta já foi separada (`palette.py`), então os detectores **já podem** ser congelados — mas só valem 0.001 na capa4 e a capa1 depende deles. Decisão de produto, não técnica | médio |

---

## G · Hipóteses MORTAS — não repetir

Três coisas parecem boas ideias, foram construídas inteiras, medidas e reprovadas. Estão aqui
para não voltarem numa próxima leitura da fila.

**G1 · Paleta adaptativa (k maior).** O `Codigo_atual.md` a listava como "endereçável, com ganho
medido", citando queda de 62%/52%/44% no erro de cor. **Esse ganho é de um proxy que não
transfere.** A/B controlado com k=16, mesmo leitor dos dois lados:

| capa | k=8 | k=16 | com `drop_films` |
|---|---|---|---|
| capa16 | 0.9202 | 0.8905 (**−0.0297**) | −0.0034 |
| capa8 | 0.9406 | 0.8270 (**−0.1136**) | −0.0039 |
| capa13 | 0.9273 | 0.9000 (**−0.0273**) | — |

Mecanismo: mais clusters = mais cor de filme anti-serrilhado sobrevive = mais peças fantasma
(capa13 vai de 19 para 43 peças). E os clusters com >1% de cobertura em k=16 são **3 a 9, não
~15**: a capa16 precisa de 7.

**G2 · Contorno sub-pixel.** Saldo **−0.0088 em 8 capas**. Ganha em curva (capa16 +0.0054) e
**colapsa componente pequeno** — os fragmentos do logo da capa2 caem de 35 para 4 pontos. Mesmo
guardado por espessura, o teto é +0.002 ao custo de mais uma constante calibrada.

**G3 · Transação no portão (agrupar edits).** Morta **duas vezes**. A história é convincente —
"remover o glifo traçado e inserir o texto só funciona em PAR" — e a medição a derruba: aplicando
os 12 edits da capa3 juntos, ela vai de 0.6146 para **0.3887**. E a classe é pequena: regiões
traçadas dentro de caixas de texto existem em 3 de 20 capas, cobrindo 2–9% de cada uma.

---

## Sequência sugerida

1. **A2** (banco de provas) → **A1** (o juiz). Nesta ordem, porque o histórico mostra o que
   acontece quando o Score muda sem banco.
2. **C1** (recall de texto) logo depois, porque ele **depende** do A1 e é o maior ganho visível.
3. **D1** (memória) e **E1** (capa no livro) a qualquer momento — são pequenos e independentes.
4. **B1** (gradiente) quando aparecer o primeiro pôster que o exija; hoje é hipotético fora do
   teste frio.

⚠️ **O que não muda com nenhum destes itens:** a fonte é um clone métrico (a real é paga), e
os tetos de tipografia miúda seguem onde estão. São premissas, não dívida.
