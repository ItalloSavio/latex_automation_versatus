# Análise das críticas de design — Versatus HPC Storage · Solution Brief

**Documento avaliado:** Versatus HPC Storage — Solution Brief v0.2 (3 páginas, A4)
**Críticas:** time de marketing (`criticas.md`, pontos A1–A10 e M1–M19)
**Resultado:** Solution Brief v0.3 (11/11/2026)

Li as 19 críticas e as confrontei com o código do brief. As medições batem com o que está no arquivo: por exemplo, o corpo de 9,83pt, os 11 tamanhos de fonte e o vermelho #EF444B com contraste de 3,75:1. Concordo com os 10 pontos fortes (A1–A10), que foram mantidos.

Das melhorias, 12 foram acatadas por inteiro. As outras 7 foram acatadas com ajuste ou dependiam de uma decisão, já tomada e aprovada.

## Resumo

| # | Ponto | Veredito |
|---|---|---|
| M1 | Escala tipográfica com 6 tamanhos | Acatado |
| M2 | Um único peso de destaque | Acatado |
| M3 | Subtítulo colado ao título | Acatado |
| M4 | Vermelho só para marca e estrutura | Acatado |
| M5 | Verde-água (teal) com um significado só | Acatado |
| M6 | Vermelho de texto com contraste 4,5:1 | Acatado, com decisão de marca |
| M7 | Linhas alinhadas entre as colunas | Acatado parcialmente |
| M8 | Equilibrar as colunas da página 2 | Acatado |
| M9 | Alinhar a caixa "Saiba mais" à tabela | Acatado |
| M10 | Alinhar o logo ao subtítulo | Acatado |
| M11 | Conter o grafismo da capa | Acatado |
| M12 | Aliviar a página 3 | Acatado parcialmente |
| M13 | Colunas iguais na tabela | Acatado |
| M14 | Rótulo "Hybrid Tiering" na seta certa | Acatado |
| M15 | Quebra do título por sentido | Acatado com ajuste (conflitava com uma regra já definida) |
| M16 | Tirar a repetição da capa | Acatado parcialmente |
| M17 | Destacar o "8 de 10" | Acatado com o dado atribuído e datado |
| M18 | Uma unidade só na linha "Escala" | Acatado com outra solução (faltava um dado) |
| M19 | Nota de rodapé e quebra de título | Acatado |

## Análise ponto a ponto

**M1 — Escala tipográfica.** Acatado. Os 11 tamanhos surgiram de ajustes feitos um a um, e os pares que diferem por menos de 1pt não criam hierarquia. Os 6 tamanhos propostos cobrem todos os papéis. O corpo passou de 9,83 para 10pt, sem impacto relevante no espaço.

**M2 — Peso de destaque.** Acatado. Era um erro: os nomes do roadmap herdavam o negrito padrão (700), enquanto os casos de uso usavam SemiBold (600).

**M3 — Subtítulo.** Acatado. O subtítulo ficava no meio do caminho entre o título e o corpo e parecia solto. Foi aproximado do título, e o peso passou de Light para Regular itálico. O itálico continua fazendo o papel do serifado itálico da IBM.

**M4 — Vermelho com três funções.** Acatado. A célula "AI Training", a caixa "Protocol Gateways" e o rótulo "Hybrid Tiering" estavam em vermelho sem nenhum significado por trás disso. Passaram para preto ou cinza. O vermelho ficou só para a marca e os títulos de seção.

**M5 — Teal.** Acatado. Ficou com um único significado, "flash / dado quente", no diagrama. A barra da nota "considere outra arquitetura" virou um fio cinza, coerente com a regra de fios do A7.

**M6 — Contraste do vermelho.** Acatado, como decisão de marca. Os títulos de seção (14,25pt em SemiBold) não chegavam a 4,5:1. O achado colateral foi o mais importante:

- **O manual de marca define #DD4F51**, assim como o template LaTeX.
- **A v0.2 usava #EF444B**, que é a cor do PNG do logo.
- **#DD4F51 também reprova:** dá 3,95:1.

Caminho adotado:

- **Cor-base:** #DD4F51, a do manual, para os preenchimentos.
- **Variante só para texto:** uma mais escura, com contraste acima de 4,5:1.
- **Logo:** continua intacto.

Ressalva: o manual diz para não alterar as cores. A variante de texto é uma decisão de marca, não de diagramação.

**M7 — Linhas alinhadas entre as colunas.** Acatado em parte.

- **Feito:** espaço entre parágrafos de uma linha inteira (15pt) e títulos de seção ocupando um número inteiro de linhas. Isso deixa as colunas em fase nos trechos de texto corrido.
- **Não garantido:** alinhamento perfeito depois de figuras, tabelas e do bloco da OpenSFS. Para isso, cada um desses elementos precisaria ter altura em múltiplos exatos de 15pt. Dá para aproximar, mas não para garantir, sobretudo numa eventual versão em LaTeX, onde a grade de linhas é notoriamente difícil.

**M8 — Página 2 desbalanceada.** Acatado. Resolvido junto com o M17 e o M19: a nota de rodapé na página 2 e o destaque "8 de 10" ocupam o branco da coluna esquerda.

**M9 — Quase-alinhamentos na página 3.** Acatado, com alinhamento exato: o topo e a base da caixa "Saiba mais" coincidem com os fios da tabela. Um erro de 1,5pt parece descuido.

**M10 — Logo e subtítulo.** Acatado. O topo do logo passou a ficar alinhado à primeira linha do subtítulo, e o fio dos Destaques ganhou respiro.

**M11 — Grafismo da capa.** Acatado. Os fios diagonais chegavam a 10pt dos bullets. O grafismo ficou contido na coluna esquerda, sangrando só para a esquerda e para baixo. Também passou a ter menos fios e mais grossos, para ter massa visual parecida com o bloco da IBM.

**M12 — Página 3 densa.** Acatado em parte.

- **Acatado:** um único elemento escuro por página. O cabeçalho preto da tabela virou texto com fio, e o bloco preto "Saiba mais" ficou como o único escuro. O roadmap encolheu para um parágrafo curto.
- **Não acatado:** levar a OpenSFS para o rodapé. O logo foi pedido "no lugar mais adequado", e ali ele ficaria pequeno e ilegível. O bloco já usava fios cinza, que é o tratamento certo para um aparte.

**M13 — Colunas da tabela.** Acatado. As três colunas comparadas ficaram com a mesma largura, e a coluna de rótulos encolheu.

**M14 — Diagrama.** Acatado. O rótulo "Hybrid Tiering" estava sobre a bifurcação e deveria estar na seta ↔ entre os dois pools. O texto interno do diagrama também subiu para os tamanhos da escala, com caixas mais largas onde foi preciso.

**M15 — Título.** Acatado com ajuste. A proposta do marketing quebrava uma regra já definida: "Versatus HPC Storage" sozinho em uma linha. Na versão deles, a última linha virava "com Versatus HPC Storage". Havia duas opções:

- **(a) Versão do marketing:** quebra 100% por sentido, mas o nome do produto deixa de ficar sozinho.
- **(b) Adotada:** quebra por sentido nas três primeiras linhas e mantém o nome sozinho. Só a terceira linha termina em palavra de ligação, contra as três da v0.2:

  > Storage paralelo
  > para treinamento de modelos
  > e simulação computacional com
  > Versatus HPC Storage

**M16 — Repetição na capa.** Acatado em parte. Era verdade que 4 dos 6 bullets do corpo repetiam os Destaques.

- **Acatado:** trocar por capacidades que os Destaques não citam: acesso POSIX/S3/NFS/SMB, InfiniBand ou Ethernet, regras de ciclo de vida por projeto/usuário/idade, I/O por job e compatibilidade com o Lustre padrão.
- **Não acatado:** "virar números". Ainda não há desempenho medido nos blueprints, e o material não deve trazer número sem prova.

**M17 — Destacar o "8 de 10".** Acatado, com uma condição. Na página 2 o destaque também resolve o M8, então não pesa contra o M12. Mas a única fonte do dado é a The Lustre Collective, uma consultoria do próprio ecossistema Lustre. A condição era conferir o dado contra a lista TOP500 atual antes de transformá-lo no número mais visível do material.

**M18 — Linha "Escala".** Acatado, mas faltava um dado. O documento aprovado só define capacidade para dois blueprints: Entry com 0,5–2 PB, e Capacity com mais de 2 PB. Não há capacidade definida para o AI Training. As saídas eram:

- **(a) Capacidade em PB nas três colunas:** exigiria a faixa do AI Training.
- **(b) Duas linhas:** "Capacidade (PB)" e "GPUs atendidas".

**M19 — Detalhes.** Acatado nos dois itens: a nota ¹ foi para o pé da página 2, e o título passou a "Os mesmos dados, / por qualquer protocolo".

## Como ficou na v0.3

Todas as decisões acima foram aprovadas, inclusive os acatos parciais. A versão 0.3 foi conferida medindo o próprio PDF:

- **Escala tipográfica (M1):** 6 tamanhos (21,5 · 14 · 12,5 · 10 · 8,5 · 7pt), mais o expoente da nota de rodapé.
- **Peso de destaque (M2):** só SemiBold, em todo o documento.
- **Linhas entre colunas (M7):** o texto corrido segue a mesma grade de 15pt nas duas colunas.
- **Página 2 (M8):** as duas colunas terminam exatamente na mesma altura.
- **Caixa "Saiba mais" (M9):** o topo e a base coincidem exatamente com os fios da tabela.

Três pontos saíram diferentes do previsto:

- **"8 de 10" (M17):** o dado não pôde ser confirmado no TOP500. A lista não informa o sistema de arquivos de cada máquina, e o Top 10 de junho de 2026 mudou, com um sistema chinês em 1º lugar e outros que não divulgam o storage. O destaque foi mantido, mas com o dado datado e atribuído: "usavam o sistema de arquivos Lustre no início de 2026, segundo a The Lustre Collective".
- **Vermelho de texto (M6):** foi usado **#D8373A** em vez do #DB343C sugerido. É o #DD4F51 do manual escurecido, com o mesmo matiz e a mesma saturação, e dá 4,64:1. Preenchimentos e o grafismo usam #DD4F51; o logo segue intacto.
- **Linha "Escala" (M18):** sem a capacidade do AI Training, a linha virou "Dimensionado por". Ela mostra o critério de cada blueprint: capacidade de 0,5 a 2 PB, throughput de 8 a 512 GPUs e capacidade acima de 2 PB.

O título usa 21,5pt, dentro do degrau "~22pt", para que a terceira linha caiba na margem.

### Cortes de texto

A grade de 15pt, com uma linha inteira entre parágrafos, ocupa mais espaço, e o texto não cabia nas três páginas. Para manter três páginas, foram cortados trechos que se repetiam:

- **Página 2:** saiu o parágrafo depois do diagrama (o que ele dizia foi para a legenda) e parte do parágrafo de suporte, que repetia a lista "Suporte e serviços" da página 3. O texto de protocolos foi enxugado, porque repetia a capa.
- **Página 3:** saiu a linha "Hardware" da tabela, porque os fabricantes já aparecem na capa. A legenda da tabela virou uma frase do parágrafo de blueprints.

Recuperar algum desses trechos exige tirar outro conteúdo no lugar.

## Fontes

- [TOP500 — Highlights, June 2026](https://www.top500.org/lists/top500/2026/06/highs)
- [Stackscale — The World's Most Powerful Supercomputers in 2026](https://www.stackscale.com/blog/the-worlds-most-powerful-supercomputers-in-2026-lineshine-takes-the-lead/)
