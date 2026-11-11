# Críticas de design — Versatus HPC Storage · Solution Brief v0.2

**Documento avaliado:** `Versatus-HPC-Storage-Solution-Brief_v0.2.pdf` (3 páginas, A4).
**Referência:** Solution Brief da IBM, "Intelligent storage management with IBM General Parallel
File System" (padrão de impressão anterior ao Carbon, época do "Systems and Technology Group").
**Critérios:** os princípios comuns ao Carbon e à IBM Design Language, que são grade rígida, escala
tipográfica curta, cor como sinal e contraste acessível. Os eixos são disposição, peso,
espaçamento e força da informação. Fontes e imagens ficaram de fora da comparação.
**Método:** os números vêm de medição direta do PDF (posição, corpo, peso e cor de cada linha;
fios, caixas e preenchimentos; contraste WCAG calculado sobre a cor renderizada). Todas as
coordenadas estão em pontos (1pt = 0,353 mm) e a origem é o canto superior esquerdo da página.

Dados de base do PDF:

| item | valor medido |
|---|---|
| página | A4, 595 × 842pt |
| margens laterais | 43,5pt dos dois lados (15,3 mm) |
| colunas (págs. 2 e 3) | 2 × 241,5pt, entre colunas 25,5pt |
| colunas (pág. 1) | lateral de 178,5pt, entre colunas 42pt, corpo de 288pt |
| corpo de texto | 9,83pt, entrelinha de 15pt (1,53) |
| cores | vermelho #EF444B · teal #4CB6B4 · preto #201F1E · cinzas #6B6867 e #BCB9B9 |

---

## O que está bom

**A1. A anatomia da página 1 é a do brief da IBM.** Cabeçalho de duas linhas no canto, título
na coluna da direita, logo e "Destaques" entre fios na coluna esquerda, corpo à direita e o
grafismo da marca sangrando no canto inferior esquerdo.

**A2. O alinhamento fino está certo.** O fio de cima dos Destaques (y = 300pt) cai no topo da
primeira linha do corpo (299,7pt). A IBM faz exatamente isso, e é o tipo de detalhe que passa
rigor.

**A3. Destaques prometem benefícios; o corpo lista capacidades.** Os Destaques começam com verbo
no imperativo (Mantenha, Pague, Opere, Escolha, Cresça, Fique), e a lista do corpo descreve
capacidades. É a mesma divisão da IBM (Increase, Maintain, Improve… contra a lista de recursos).

**A4. Margens e colunas são disciplinadas.** As margens são iguais (43,5pt) dos dois lados, as
colunas das páginas 2 e 3 são idênticas (241,5pt) e os títulos de seção das duas colunas
assentam na mesma linha de base (96pt) nas duas páginas.

**A5. O corpo de texto lê bem.** São 9,8pt com entrelinha de 1,53 e de 55 a 70 caracteres por linha,
dentro da faixa ideal de leitura (45–75). É compatível com o corpo de texto longo do Carbon
(entrelinha de ~1,5).

**A6. Os títulos de seção ficam colados ao próprio texto.** Há 34pt de espaço acima do título e
19pt abaixo, então cada seção se lê como um bloco, que é a proximidade correta.

**A7. Os fios seguem uma regra.** Fio preto enquadra exibição (Destaques, figura, tabela) e fio
cinza enquadra aparte (OpenSFS, rodapé). Ecoa a IBM emoldurando a foto entre fios.

**A8. Um diagrama no lugar de foto de banco de imagens.** A IBM usa imagem decorativa; o
diagrama de arquitetura carrega informação, e isso dá mais força ao documento.

**A9. O contraste do texto é excelente.** O corpo (#201F1E sobre branco) tem 16,5:1 e o cinza
das legendas (#6B6867) tem 5,5:1. Os dois passam com folga.

**A10. O fecho é forte.** "Para quem é", com o honesto "considere outra arquitetura", dá
credibilidade, e o bloco "Saiba mais" fecha com uma chamada para contato clara.

---

## Melhorias, por impacto

### Peso e hierarquia

**M1. A escala tipográfica tem 11 tamanhos.**
Os tamanhos são 21,75 · 14,25 · 12,75 · 12,38 · 9,83 · 8,70 · 8,62 · 8,25 · 7,88 · 7,12 · 6,75pt. Os trios
8,70/8,62/8,25 e 7,88/7,12/6,75 e o par 12,75/12,38 estão a menos de 1pt um do outro. O olho não
distingue diferenças assim, então elas não criam hierarquia e só parecem descuido.
*Critério IBM:* uma escala curta e fixa, com um papel por degrau.
*Proposta:* 6 degraus.

| papel | corpo |
|---|---|
| título | ~22pt |
| seção | ~14pt |
| subtítulo e rótulo ("Destaques") | ~12,5pt |
| corpo | ~10pt |
| pequeno (destaques, tabela, cabeçalho, aparte) | ~8,5pt |
| nota (legenda, diagrama, texto legal) | ~7pt |

**M2. Há dois pesos de destaque para a mesma função.**
Na página 3, "Research computing." está em SemiBold e "Parallel Namespace Search" está em Bold.
*Critério IBM:* o Carbon destaca com um peso só, o SemiBold.
*Proposta:* unificar em SemiBold.

**M3. O subtítulo fica solto entre o título e o corpo.**
O subtítulo está a 47pt da última linha do título e a 58pt da primeira linha do corpo, quase no
meio do caminho, então ele não parece pertencer ao título. Na IBM ele fica colado ao título: a
distância até o título é cerca de metade da distância até o corpo. O peso Light também o deixa
mais fraco que o próprio corpo de texto.
*Proposta:* aproximar o subtítulo do título (~20–24pt) e manter o respiro até o corpo; considerar
o peso Regular.

### Cor

**M4. O vermelho faz três trabalhos ao mesmo tempo.**
- **Marca:** título, grafismo e os quadradinhos dos Destaques.
- **Estrutura:** os 9 títulos de seção.
- **Destaque:** a célula "AI Training", a caixa "Protocol Gateways" e o rótulo "Hybrid Tiering".

Quando tudo é vermelho, o destaque não destaca. Por que "AI Training" é vermelho? É uma
recomendação? Por que "Protocol Gateways"?
*Critério IBM:* a cor é um sinal, usada com parcimônia, e cada cor tem um significado.
*Proposta:* vermelho para marca e estrutura. Destaques dentro da tabela e do diagrama em preto ou
cinza, ou removidos.

**M5. O teal aparece duas vezes, com dois significados.**
Ele marca "dado quente" no Pool flash do diagrama e marca "aparte" na barra da nota da página 3.
*Proposta:* escolher um significado só.

**M6. O vermelho não passa no contraste quando vira texto pequeno.**
O #EF444B tem **3,75:1** sobre branco.
- O título passa, porque texto grande (≥ 18pt) tolera menos contraste.
- Os títulos de seção, a 14,25pt em SemiBold, ficam abaixo dos 4,5:1 exigidos.
- O pior caso é o texto branco de 8,25pt sobre a célula vermelha da tabela e o rótulo "Hybrid
  Tiering" em vermelho a 6,75pt.

*Critério IBM:* o Carbon exige 4,5:1 em texto, e o vermelho dele (#DA1E28) dá 5,0:1.
*Proposta:* um vermelho próprio para texto, como **#DB343C** (4,6:1), mesmo matiz e um tom mais
escuro. O vermelho de preenchimento (grafismo, bullets) pode continuar como está.
⚠️ *Achado colateral:* a paleta do template do livro (`styles/versatus-colors.sty`) define
`VSRed` = **#DD4F51** (3,95:1), e o PDF usa **#EF444B**. São dois vermelhos de marca diferentes.
Teal, prata e preto batem exatamente com o template; só o vermelho diverge.

### Espaçamento

**M7. As linhas de texto não se alinham entre as colunas.**
O espaço entre parágrafos é de 24pt para uma entrelinha de 15pt, ou seja, 1,6 linha. Depois do
primeiro parágrafo, as colunas saem de fase. Na página 2, por exemplo, linhas vizinhas assentam
em 146,2pt e 144,8pt.
*Critério IBM:* na escola suíça e na grade da IBM, as linhas das colunas vizinhas coincidem.
*Proposta:* espaço entre parágrafos de uma linha inteira (15pt), e títulos de seção ocupando
múltiplos da entrelinha.

**M8. A página 2 está desbalanceada.**
A coluna esquerda termina em 707pt e a direita em 779pt, cerca de 5 linhas de diferença e
~70pt de branco embaixo, só na esquerda. Na referência, as duas colunas da página 2 fecham na
mesma altura.

**M9. Há quase-alinhamentos na página 3.**
O topo da caixa "Saiba mais" está a 556,5pt e a linha da tabela ao lado está a 555,0pt; a base
da caixa está a 686,2pt e o fio final da tabela a 673,5pt. Um alinhamento que erra por 1,5pt ou
por 13pt parece descuido.
*Proposta:* ou alinhar exato (base da caixa = fio final da tabela), ou afastar de propósito.

**M10. O logo está desalinhado do subtítulo.**
O logo ocupa 238–279pt e o subtítulo 224–255pt, então o logo fica mais baixo e a apenas 21pt do
fio dos Destaques. Na IBM, o logo fica na mesma altura do subtítulo.
*Proposta:* alinhar o topo do logo à primeira linha do subtítulo, ou a base dele à última linha.

**M11. O grafismo da página 1 invade o espaço entre as colunas.**
Os fios diagonais vão até x = 253,5pt. A coluna dos Destaques termina em 222pt e o corpo começa
em 264pt, então os fios passam a 10pt dos bullets, na mesma altura deles. Na IBM, o bloco do
logo fica contido na coluna esquerda e sangra só para fora da página. Outra diferença é o peso
visual: o bloco da IBM é maciço e equilibra o título na diagonal, enquanto o nosso tem duas
formas cheias e cinco fios de 1pt.
*Proposta:* conter o grafismo em x ≤ 222pt, ou sangrar só para a esquerda e para baixo, e
considerar fios mais grossos ou em menor número.

### Disposição

**M12. A página 3 está densa.**
São 6 seções, o aparte da OpenSFS com logo, a tabela, a nota, a lista, o bloco "Saiba mais" e o
rodapé legal. Quatro elementos chamam atenção ao mesmo tempo (cabeçalho preto da tabela, célula
vermelha, barra teal, bloco preto), e as duas massas pretas ficam lado a lado, competindo. A
referência respira: texto e um elemento visual por página.
*Proposta:* um elemento escuro por página, e cortar ou encolher algo. Por exemplo, "O que vem a
seguir" em uma linha, ou a OpenSFS como uma linha no rodapé.

**M13. As colunas da tabela que se comparam têm larguras diferentes.**
Entry, AI Training e Capacity medem 72 / 54,8 / 61,5pt, e por isso "AI Training" e "Capacity"
quebram em 3 linhas.
*Proposta:* a mesma largura para as três; a coluna de rótulos (53pt) pode encolher.

**M14. No diagrama, o rótulo "Hybrid Tiering" está no lugar errado.**
Ele está sobre a bifurcação Dados → pools, mas o tiering é a seta ↔ entre o Pool flash e o Pool
de disco, que ficou sem rótulo. Os textos internos do diagrama, de 6,75–7,1pt em cinza, estão no
limite de leitura impressa.
*Proposta:* mover o rótulo para a seta ↔ e subir os textos do diagrama para o degrau "nota" do M1.

### Força da informação

**M15. O título tem 4 linhas, e todas terminam em palavra de ligação.**
O título está quebrado assim: "Storage paralelo **para** / treinamento de modelos **e** /
simulação computacional **com** / Versatus HPC Storage". São 92 caracteres, contra 68 no título
da IBM.
*Proposta:* quebrar por sentido, ou encurtar (o nome do produto já está no cabeçalho). Com a
quebra por sentido, fica assim:

> Storage paralelo
> para treinamento de modelos
> e simulação computacional
> com Versatus HPC Storage

**M16. A página 1 diz a mesma coisa duas vezes.**
4 dos 6 bullets do corpo (tiering, console, blueprints Lenovo/Supermicro/Gigabyte, suporte 24×7)
repetem os Destaques ao lado.
*Proposta:* os bullets trazem o que os Destaques não dizem (por exemplo, POSIX/S3/NFS/SMB e
throughput) ou viram números.

**M17. O dado mais forte está escondido.**
"8 dos 10 maiores supercomputadores do mundo" está no meio de um parágrafo da página 2.
*Proposta:* promover o dado a número em destaque ("8 de 10"). Pesar contra o M12: é um elemento
a mais.

**M18. A linha "Escala" da tabela não compara.**
Ela diz "0,5 a 2 PB" · "Pods de GPU" · "Vários PB": a coluna do meio usa outra unidade, e uma
tabela de comparação perde força quando a linha não compara.
*Proposta:* uma unidade só (PB ou número de GPUs) para as três colunas.

**M19. Detalhes.**
- A nota de rodapé ¹ é chamada na página 2 e resolvida na página 3. Ela deveria ficar no pé da
  página 2.
- O título "Os mesmos dados, por qualquer / protocolo" deixa uma palavra sozinha na segunda linha.
  Basta rebalancear: "Os mesmos dados, / por qualquer protocolo".

---

## Seleção — marque o que entra na versão LaTeX

- [ ] M1 — escala tipográfica em 6 degraus
- [ ] M2 — um peso de destaque (SemiBold)
- [ ] M3 — subtítulo colado ao título
- [ ] M4 — vermelho só para marca e estrutura
- [ ] M5 — teal com um significado só
- [ ] M6 — vermelho de texto com contraste 4,5:1 (e unificar com o `VSRed` do template)
- [ ] M7 — linhas alinhadas entre colunas
- [ ] M8 — balancear as colunas da página 2
- [ ] M9 — alinhar a caixa "Saiba mais" à tabela
- [ ] M10 — alinhar o logo ao subtítulo
- [ ] M11 — conter o grafismo da página 1
- [ ] M12 — aliviar a página 3
- [ ] M13 — colunas iguais na tabela
- [ ] M14 — rótulo "Hybrid Tiering" na seta certa
- [ ] M15 — quebra do título por sentido (ou encurtar)
- [ ] M16 — tirar a repetição da página 1
- [ ] M17 — promover o "8 de 10"
- [ ] M18 — unidade única na linha "Escala"
- [ ] M19 — nota de rodapé e título de seção
