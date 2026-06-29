# Versatus HPC LaTeX Templates — documentação geral

Este documento define a política comum para os templates técnicos da Versatus HPC.

## Modelo de compilação

Cada produto documental deve ter uma única fonte de conteúdo e múltiplos arquivos-raiz. O conteúdo fica em `main.tex` e nos diretórios `frontmatter/`, `chapters/` e `backmatter/`. Cada arquivo-raiz apenas seleciona uma variante.

Exemplo:

```tex
\def\VSDocumentVariant{standard}
\def\VSCoverOption{A}
\input{main}
```

Essa arquitetura evita duplicação de conteúdo e permite gerar todas as versões por automação externa, sem `shell-escape` e sem acoplamento inseguro entre compilações.

## Variantes obrigatórias

### `standard`

Versão editorial padrão, com fundo branco, capa colorida, acentos cromáticos e símbolo colorido no rodapé.

### `print`

Versão de impressão, com fundo branco, capa monocromática, links pretos e símbolo preto no rodapé.

### `longread`

Versão de leitura prolongada, com fundo warm `#FCFAF2`, capa colorida, acentos cromáticos e símbolo colorido no rodapé.

### `longread-mono`

Versão de leitura prolongada sem cores fortes, com fundo warm `#FCFAF2`, capa monocromática, links pretos e símbolo preto no rodapé.

## Comandos de build

Cada template deve conter:

```text
build-all.sh
build-all.ps1
Makefile
latexmkrc
```

Comandos esperados:

```bash
./build-all.sh
make all
make standard
make print
make longread
make longread-mono
```

## Identidade visual

A paleta institucional usada nos templates é:

```text
VSTeal   #4CB6B4
VSSilver #BCB9B9
VSRed    #DD4F51
VSBlack  #201F1E
```

O fundo warm padrão é:

```text
VSWarmPaper #FCFAF2
```

Ele foi escolhido como off-white quente, praticamente neutro, para leitura longa sem produzir aparência envelhecida ou decorativa.

## Tipografia

A preferência tipográfica é Source Sans Pro, em alinhamento com a identidade visual da Versatus. Quando não estiver instalada, o template usa fallbacks seguros:

```text
Source Sans 3 -> Noto Sans -> TeX Gyre Heros -> Latin Modern Sans
```

Não distribuir arquivos de fonte nos pacotes.

## Uso do logotipo e símbolo

O logotipo horizontal é usado em capas e marcas d'água discretas. O símbolo é usado no rodapé. A marca deve ser usada sem rotação, sem distorção, sem sombra, sem contorno e sem alteração manual de proporções.

## Critérios mínimos de aceite

Cada template deve:

1. Compilar com LuaLaTeX.
2. Gerar as quatro variantes.
3. Ter capa colorida e capa monocromática.
4. Usar marca d'água discreta em preto e branco.
5. Usar o símbolo no rodapé, colorido ou monocromático conforme a variante.
6. Manter conteúdo único, sem duplicação entre versões.
7. Ter documentação de uso e comandos de build.
8. Não depender de `shell-escape`.

### Rodapé e contador de páginas

As páginas internas usam o símbolo Versatus HPC no rodapé e o contador central no formato `Página X de Y`. O valor `Y` é calculado como total absoluto de páginas do PDF, não apenas como o último número visível da paginação.

### Capa e marca d’água

As capas coloridas devem usar a versão correta do logotipo para o respectivo fundo. Em capas escuras, usar `vs-horizontal-fundo-preto.png`; em capas claras, usar `vs-horizontal-principal.png`; em capas monocromáticas de impressão, usar `vs-horizontal-preto-1cor.png`. A marca d’água decorativa no canto inferior direito da capa foi removida para manter a capa mais limpa. A marca d’água permanece nas páginas internas, em tamanho maior e com baixa opacidade.

## Exemplos internos mínimos

O template de livro deve manter três capítulos de exemplo suficientemente ricos para validar composição editorial antes da escrita real. A cobertura mínima inclui tabelas pequenas, médias e grandes; equações pequenas, médias e multilinha; gráfico individual; dois gráficos lado a lado; quatro gráficos em matriz 2 x 2; fotografia centralizada; fotografia com texto lateral; blocos em duas, três e quatro colunas; e três parágrafos contínuos.

Esses exemplos devem ser tratados como material de demonstração. Em um projeto real, o autor pode apagar os capítulos e preservar apenas a estrutura, os ambientes e os comandos de build.


## Ambientes editoriais adicionais

Os exemplos internos incluem ambientes para código e matemática formal. Para código, use `VSTerminalCode` quando a composição deve simular um terminal escuro e `VSCodeBlock` quando o código deve aparecer em fundo claro. Para matemática formal, use `theorem`, `lemma`, `corollary` e `proof`. Para ênfase editorial, use `VSImportant`, `VSImportantGray` ou `VSImportantColor`.

A implementação evita `minted` deliberadamente. Isso mantém o template portável, sem `shell-escape` e sem dependência externa de Python/Pygments.
