# pos-mvp — o que fazer depois do MVP

> Escrito em **2026-09-14**, no fechamento do MVP de 9 capas.
> Cada item traz **a evidência medida** que o motiva, não a intuição. Onde um número aparece,
> ele saiu de uma rodada real — e onde uma hipótese morreu na medição, isso está registrado,
> porque saber o que **não** fazer vale tanto quanto a fila.
>
> Estado na entrega (14/09): 9 capas, média **0.9003**, auditoria **9/9**, portão **8/9 OK**.
>
> **Estado em 30/09: média 0.9034 · QUATRO em ≥ 0.95 · portão 8/9 OK · auditoria 9/9.**
> O motor atingiu platô **neste corpus** (8 das 9 no teto de resolução da fonte, e as capas NÃO
> podem ser reexportadas). O trabalho agora é robustez + produto — ver **"Plano em fases"** no fim.
> **Fase 1 FEITA em 30/09** (E1 com `--livro`, `--dpi` automático, D1, progresso visível); as
> Fases 2 e 3 aguardam a orientação do usuário. Achado da Fase 1: o próximo muro para capa em
> alta é o TEMPO por render — duas causas medidas, com conserto pequeno e resultado idêntico.

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

> **Estado em 28/09:** o `ATENCAO` da capa8 FECHOU — a causa não era o juiz nem o traçado, era o
> `_measure_ink` cego a polaridade (título claro sobre fundo escuro medido pelo fundo, 48% grande
> demais, e por isso apagado pelo `_select_text`). O `ATENCAO` da capa1 é a mesma causa.
>
> **Estado em 17/09:** A2 ✅ feito (16/09). A1 **parcial, por decisão**: o `accept.py` passou a ver
> conteúdo AUSENTE (16/09, contra a referência congelada) e palavras COLADAS em tipo de display
> (17/09). O Score **não** foi trocado — repesar deu 2/3 no banco e três casos não calibram peso.
> O juiz novo entrou como PORTÃO. Detalhe e números no `CLAUDE.md`.

### A2 · Reescrever o `judge_bench.py`  `pequeno` · **pré-requisito do A1** · ✅ FEITO 16/09

Não existia. O banco de provas que validava o juiz contra os vereditos já dados pelo usuário
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

> **Reenquadrado em 25–28/09:** o que o upscale tentava comprar, a **resolução real** entrega —
> capa2 a 2,93× leu 18 elementos contra 12, com confiança 0,91 contra 0,70 (§D2). E das três
> causas downstream, uma caiu: a regra de parágrafo + a correção de polaridade fazem o
> `_measure_ink` parar de pegar mais que o glifo. Restam os fragmentos e o portão de texto.
> ⚠️ Como as 9 NÃO podem ser reexportadas, este item volta a ser o único caminho de recall
> nelas — mas o ganho esperado é pequeno, porque o limite é o pixel, não o detector.

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

### D1 · Memória do quantizador  `pequeno` · ✅ **FEITO 30/09 (Fase 1)**

**Fechado:** `_nearest_palette` quantiza em blocos de linhas (orçamento de 64 MB) nos três
pontos (`structural_reader` ×2, `visual_comparator.structural_match`). Provado ANTES de tocar no
código: índice **byte-idêntico** à expressão única em 31 casos (as 9, os dois pôsteres em alta;
paleta real, a do comparador e uma de 16 cores); depois, o leitor e o `structural_match` de HEAD
contra os de agora saem **idênticos** nas 9 e no pôster, com e sem `drop_films`. Pico de memória
no pôster de 1728×2464: **780 MB → 168 MB** com k=8, **1,56 GB → 160 MB** com k=16. Tempo igual.
⚠️ O pico do PROCESSO na rodada do pôster segue em ~3,7 GB — não é o quantizador, é de antes
(o OCR do EasyOCR/torch sobre 4,3 MP é o candidato; não medido isoladamente).

`((a[:,:,None,:] - pal)**2).sum(3)` materializava `h × w × k × 3` em float32 de uma vez:

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

### ✅ MEDIDO E CONFIRMADO (2026-09-23/25) — e o efeito é maior do que este item previa

O "se algum dia houver acesso" aconteceu: o usuário reexportou a capa2 a **2,93×**
(600×815 → 1760×2390) e mandou um pôster inédito a 209 dpi. Resultado do A/B de leitura:

```
capa2, so o estagio 1        BAIXA (73 dpi)   ALTA (213 dpi)
elementos lidos                     12             18
confianca media                   0.70           0.91
conf >= 0.90                    4 (33%)       12 (67%)
conf < 0.50                          3              0
```

Nove strings corrompidas foram corrigidas **sem VLM nenhum**, e três estavam irreconhecíveis
(`'Brama dc Cstudos'` → `'Material técnico de formação; referência'`).

⚠️ **A conclusão que inverte a intuição, e que este item não previa: a capa2 em ALTA SEM VLM
supera a capa2 em BAIXA COM VLM.** Resolução compra mais que a API — e se paga uma vez.

**O piso está medido:** agrupando as 73 linhas das 9 por altura, até 16px a confiança fica em
0,70–0,81 com até 25% de strings corrompidas; a partir de 16px é 0,99 e **zero** corrompidas.
É o mesmo 16px que o `word_collisions` achou por outro caminho.

**8 das 9 capas estão no teto** (56–89 dpi; 50 a 92% das linhas abaixo do piso). A capa19
marca 0% e é engano: as linhas pequenas dela nunca foram lidas.

**O que entrou:** `cover_assembler._report_resolution` mede e AVISA (não conserta), e o
`accept` reporta como contexto sem mexer no veredito. Ver a seção correspondente no `CLAUDE.md`.

**O que NÃO entra, e é decisão fechada:** processar a imagem para "melhorá-la". Ampliar por
interpolação já está medido e reprovado (§G), e super-resolução por IA é pior por motivo
estrutural — **a imagem original É o gabarito**, então alterá-la move o alvo, e o pipeline
deriva corpo/peso/cor MEDINDO a tinta. O caminho é reexportar a fonte.

**~~A decisão de produto que fica aberta: reexportar as outras capas.~~ FECHADA em 30/09:**
as capas **não podem** ser reexportadas ("foram entregues assim"). O teto de resolução é
**permanente para estas 9**. Ganho de resolução só vale para capas NOVAS que já cheguem em alta
— e é por isso que D1 e o `--dpi` automático viraram prioridade: é exatamente onde elas mordem.

---

## E · Integração e ferramental

### E1 · Provar a capa DENTRO do livro  `pequeno` · ✅ **FEITO 30/09 (Fase 1)**

```bash
python automation/scripts/cover_pipeline.py capas_teste/capa_teste4.png --livro
#   replica (reusa) -> integra -> styles/versatus-dynamic-cover.tex (backup da anterior)
#   -> latexmk main.tex -> build/pdf/main.pdf        3m33s, com a replica ja pronta
```

**Medido com a capa4:** a página 1 do livro contra o `integrated.png` avulso difere em **0,37%**
dos pixels (média 0,46 RGB — anti-serrilhado e a esticada de 0,5%); as **páginas 2–20 saem
pixel-idênticas** ao livro como estava (a capa Kosen); fontes embutidas na capa: TeX Gyre Heros
regular e bold, as mesmas com que a réplica foi medida; nenhum aviso novo no log. A capa Kosen
anterior está em `automation/output/_backup_e1/` (e no git).

**Quatro adaptações** (`cover_integrator.book_cover_tex`), porque o tikz é feito para uma página
avulsa do tamanho do canvas: âncora em `(current page.south west)` por overlay; esticada ao A4
(o canvas tem a proporção da imagem, 29,56 cm); `\sffamily` local = a cadeia de fontes do
replicador (o livro usa outra sans); e **espaços** — `\definecolor{…}  % comentário` deixa um
espaço antes do `%`, que na página avulsa (modo vertical) some e dentro da caixa (modo LR) vira
cola: 9 cores empurravam o desenho **0,9 cm** e o comprimiam a 95,6% (11% dos pixels errados).

**O E1 achou DOIS defeitos na Fase 7 que número nenhum via:**
- ✅ **`apply_art` movia a CAIXA e não o BASELINE** — e o gerador desenha pelo baseline. A
  penalidade de layout (que lê caixas) media a composição do cache enquanto a página saía na
  composição fresca. Invisível enquanto as duas coincidiam; depois das promoções de 17/09 e
  28/09 a capa4 saiu com as cinco linhas do rodapé colapsadas em duas **com sobreposição medida
  0.0**. Corrigido: o baseline acompanha a caixa. A capa4 volta ao layout aprovado de 14/09.
- 📋 **`apply_art` casa linhas por POSIÇÃO dentro do papel** e supõe que o número de linhas não
  muda. Na capa8 a composição de hoje quebra o subtítulo em duas linhas; o cache tem um bloco
  `sub`; a segunda linha fica na posição fresca e se intercala com o rodapé. A penalidade ACUSA
  (0.0472). Vai acontecer também em uso legítimo — um metadata mais longo em outro livro. Hoje o
  contorno é `--recompose`; o conserto é reposicionar o BLOCO (re-fluir as linhas dentro da caixa
  guardada) ou invalidar a entrada quando a estrutura muda. Integrados da capa8 restaurados.

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
| ~~O cache do VLM guarda propostas JÁ processadas pelo snap~~ ✅ **FECHADO 18/09 — era a causa-raiz de três "regressões"** | No `_vlm_pass`, o cache era gravado DEPOIS do `snap_text_adds` e todo rebuild aplicava o snap de novo (não idempotente). Consequência medida: **nenhuma capa cujo entregável veio de uma rodada fresca do VLM podia ser reproduzida pelo próprio cache** — nem com o código de antes de 17/09 (capa6 pelo cache: 0.9501, sem `with`/`and boy's life`, contra 0.9524 entregue). Foi isso que fez o rebuild de 17/09 parecer regredir a 6, a 8 e a 19. Corrigido: entrada que já tem `font_size_pt` é aplicada como está, e o cache novo guarda a proposta CRUA. Prova: capa6 pelo cache com o código novo → 7/7 textos idênticos ao entregue, Score 0.9524, 0,06% dos pixels diferentes | ✅ |
| **Endereçamento por ÍNDICE** — guarda ENTROU; a CAUSA que liguei a ela estava ERRADA | Eu escrevi que a capa19 caía 0.9040→0.8877 porque `assign_ids` numera por ORDEM e o cache guardava o índice. **Medido peça a peça nos arquivos reais, não procede:** dos 35 edits do cache entregue, **32 caem na MESMA peça**, 2 não têm id, **1** aponta para peça que sumiu (vira no-op) e **ZERO** caem no vizinho. Eu inferi o deslize de a lista ter mudado de 21 para 23 regiões — as três novas entram DEPOIS, então nenhum id citado foi afetado. **A guarda entrou assim mesmo** porque índice é endereço frágil por construção e o sintoma da falha não é erro, é um edit correto na peça errada: `anchor_edits` grava centro+tamanho+string e `resolve_anchors` re-endereça, descartando com log quando não há alvo. Custo zero nos dados de hoje (no-op). Provado em unitário; ao vivo, o replay reproduz a rodada fresca edit por edit até a 4ª casa | ✅ guarda |
| **capa19: −0.0163 no rebuild, causa ainda NÃO estabelecida** (reaberto 21/09) | Três hipóteses MORTAS por medição: não é o laço (`mp=0` e `mp=3` dão 0.8877), não é o duplo-snap (o cache dela tem **zero** entradas pós-snap) e não é deslize de índice (32/35 na mesma peça). O que sobra, medido: a **análise-base mudou** — 21 → 23 regiões, a régua fina `r10` (6,87×0,04cm) existe no entregue e **não existe** no rebuild, e uma peça `rectangle` virou `polygon`. O leitor de hoje lê a capa19 diferente do que a produziu. **Próximo passo: isolar o LEITOR, não o cache** | médio |
| **Palavras coladas em tipo MIÚDO são invisíveis** (achado 17/09) — ⚠️ **REENQUADRADO 25/09: é TETO DE FONTE, não defeito do detector** (§D2: 8 das 9 capas abaixo do piso; com a fonte em alta o detector passou a funcionar sozinho em corpo de texto) | O `accept.word_collisions` só opina com linha ≥ 16px na imagem-fonte. No cabeçalho da capa2 (~7px de linha) um rebuild colou `"SÉRIE /"` em `"Versatus HPC…"` — visível no render, abaixo da resolução da medição (§D2). Mesma causa-raiz das colisões grandes: cada linha julgada na PRÓPRIA janela, e janelas vizinhas se sobrepõem | médio |
| ~~Aterramento aceita edit que não muda nada~~ ✅ **FECHADO 28/09** (`debc681`) | `_noop_reason` recusa no aterramento, sem render. 48 renders desperdiçados só nos logs daquela semana. capa12 termina em 0.9588 idêntico, com as 2 recusas esperadas | ✅ |
| **capa8: um `text.string` ERRADO do cache do VLM passou a entrar** (28/09) | Com a polaridade corrigida, a caixa mudou, o `text_match` mudou, e um edit já gravado no cache — antes rejeitado — foi aceito: a linha de y=9.29 lê `'213 park avenue south, new york city'` onde deveria ler `"upstairs at max's kansas city"`. Não colide, mas é conteúdo errado. O cache guarda propostas antigas; uma rodada FRESCA do VLM provavelmente não repropõe isso | pequeno |
| **capa1: correção de polaridade pendente** | Muda 9 elementos dela, inclusive o título que é o último `ATENCAO`. Não foi rodada porque o entregável é cirurgia manual e pede tratamento próprio (`merge_capa1`) | médio |
| **4 letras fantasma no pôster em alta** | A máscara de réguas (28/09) consertou 3 de 8; nas restantes a régua da grade encosta no glifo e a sonda de 4px não separa. Só aparece acima de ~150 dpi | médio |
| **`apply_art` supõe número de linhas fixo por papel** (achado no E1, 30/09) | Ver E1. capa8: subtítulo em 2 linhas × 1 bloco `sub` no cache → intercala com o rodapé, penalidade 0.0472. Contorno: `--recompose` | pequeno |
| ~~`audit.py` sem argumentos quebra~~ ✅ **FECHADO 30/09** | Desde 23/09 as pastas `capa_teste_ideal*` davam `int("")` → `ValueError` na auditoria inteira, e o `accept.py` contava a `ideal2` como uma segunda capa2. Agora só pastas numeradas | ✅ |
| ~~`cover_pipeline --out-dir` com outro nome~~ ✅ **guarda 30/09** | O replicador grava em `<pai>/<nome-da-imagem>`; com outro nome a réplica inteira rodava e só no fim o comando acusava "não produziu analysis.json". Agora recusa na hora e diz o caminho certo | ✅ |
| Arquivo `--brand` solto na raiz do repositório | 171 bytes, de 08/07 — sobra de um comando em que `--brand` virou nome de arquivo. Não é meu; candidato da limpeza (Fase 2) | pequeno |
| capa2: wordmark traçado e placeholder se sobrepõem | O `logo.mark` escreveu `Versatus (Logo)` mas o `vers` traçado pelo leitor continua embaixo | pequeno |
| capa6: três linhas que o OCR NUNCA leu | `wednesday`, `october 6 1993`, `east of mass. on 15th st.` — não estão nem na referência, então nenhuma medida as cobra. O passe de refinamento as VIU e adicionou (`october 6 1993` com box_local 1.000), mas as adições colidiram com blocos existentes e a rede de segurança reverteu tudo. É o caso-alvo da próxima iteração do refinamento | médio |
| `text.add` de uma linha nasce regular e assentado no fundo da caixa | `apply_edit` segue a convenção "linha solta = regular" e usa a base da caixa como linha de base. Para uma palavra de título isso dá peso e altura errados, que só `text.weight`/`text.move` seguintes corrigem — e na capa19 a correção de corpo que veio depois sobrecorrigiu | pequeno |
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

## Plano em fases — acordado com o usuário em 30/09

A "sequência sugerida" de 14/09 que estava aqui foi cumprida ou reenquadrada (A2 feito, A1
parcial por decisão, C1 reenquadrado pela resolução, B1 bloqueado sem caso de teste). O plano
agora é de **produto**, porque o motor atingiu platô neste corpus:

**Fase 1 — fechar a cadeia do produto** ✅ **FEITA 30/09**
1. ✅ **E1** — `cover_pipeline.py <imagem> --livro` integra, instala a capa em
   `styles/versatus-dynamic-cover.tex` (backup em `automation/output/_backup_livro/`) e compila o
   livro. Capa4 no livro: 0,37% dos pixels diferentes da capa avulsa, páginas 2–20 idênticas.
   Achou dois defeitos da Fase 7 (ver E1): um corrigido, um na fila (F).
2. ✅ **`--dpi` automático** — `replicate_cover.render_dpi()`: a resolução da fonte, piso 150. As 9
   ficam em 150 (fontes de 56–89 dpi, auditoria 9/9 delta zero); o pôster sai a 210, o valor que
   eu passava à mão. Todo ponto que renderiza para COMPARAR com a fonte usa a mesma função — o
   laço, o portão do VLM (`edit_gate.cover_measure`), `refine_replica`, `audit`, `judge_bench`
   e `render_analysis` —, senão mediriam em quadros diferentes.
3. ✅ **D1** — ver D1: byte-idêntico, pico de 780 MB → 168 MB no pôster.
4. ✅ **Progresso visível** — `_progresso.md` na pasta da capa, reescrito a cada etapa, render e
   linha de log (etapa k de N, tempo por etapa, renders, Score atual, última atividade, hora da
   última escrita); cabeçalhos do console com o tempo decorrido; stdout com line-buffering (num
   pipe o Python bufferizava tudo até o fim); o `cover_pipeline` grava o veredito do portão no
   mesmo arquivo; o `_run_status.md` do `run_batch` aponta para ele. Sem ETA de propósito: o
   estágio do VLM varia 10× entre capas e um número inventado é pior que nenhum.

**Achados da Fase 1 que NÃO eram dela — o próximo muro é o TEMPO por render** (medido 30/09).
Com a memória e o quadro resolvidos, o pôster em alta roda — mas a ~4–5 min por render (máquina
disputada), e uma capa leva de 26 a 71 renders: horas, contra os 30 min aceitáveis. Duas causas,
as duas com prova de que o resultado não muda:

| causa | medido | conserto proposto |
|---|---|---|
| `_background_color` e `_pal` do comparador usam `np.unique(axis=0)`, o caminho LENTO do numpy (ordena linhas RGB), e o `compare()` chama isso ≥2× por render na imagem inteira e 1× por caixa de texto | pôster **41,9 s → 0,39 s** por chamada (107×), capa8 4,8 s → 0,034 s; mesma cor, mesma ordem de desempate (RGB empacotado num inteiro + `bincount`) | pequeno |
| o wrapper testa `Helvetica Neue` → `Helvetica` → `TeX Gyre Heros`; as duas primeiras não existem aqui, e cada consulta falha faz o `luaotfload` **reconstruir o banco de fontes** ("Reload initiated") — duas vezes por render, porque o LuaLaTeX roda 2× | capa8: **75 s → 21 s** por compilação com a fonte resolvida direto, PDFs **pixel-idênticos**. Já estava no `cover.log` de 28/09 — custo antigo, não regressão | pequeno — resolver a cadeia UMA vez por sessão e escrever só a fonte que existe |

Perfil de um render do pôster (com cProfile e máquina disputada, então os absolutos estão
inflados): LuaLaTeX 102 s + `compare()` 399 s, dos quais `_background_color` 141 s,
`structural_match` 133 s (`_pal` 81 s dentro dele), `_content_split` 75 s.
⚠️ Nenhum dos dois consertos foi aplicado: não eram da Fase 1 e esperam a decisão do usuário.

**Fase 2 — limpeza e documentação oficial** ⏸️ aguarda orientação do usuário.

**Fase 3 — CLI guiada** ⏸️ aguarda orientação do usuário. O usuário conhece CLI, mas não sabe
que comando rodar — o foco é descobribilidade: o que rodar, em que ordem, o que cada veredito
significa.

⚠️ **O que não muda com nenhum destes itens:** a fonte é um clone métrico (a real é paga), e
os tetos de tipografia miúda seguem onde estão. São premissas, não dívida.
