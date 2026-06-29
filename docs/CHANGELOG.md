# Changelog

## v0.2.3

- Adicionados exemplos internos para blocos de código em estilo terminal: pequeno, médio e grande.
- Adicionados exemplos internos para blocos de código em fundo claro: pequeno, médio e grande.
- Adicionados exemplos de enunciação de teorema, lema e corolário.
- Adicionada prova de teorema matemático usando o ambiente `proof`.
- Adicionados três ambientes de destaque textual: `VSImportant`, `VSImportantGray` e `VSImportantColor`.
- Implementação de código baseada em `listings` + `tcolorbox`, sem `minted`, sem `shell-escape` e sem dependência externa de Pygments.
- Adicionados os capítulos `04_capitulo_modelo.tex` e `05_capitulo_modelo.tex`.

## v0.2.2

- Corrigida a capa colorida escura para usar a versão do logotipo preparada para fundo escuro: `vs-horizontal-fundo-preto.png`.
- Removida a base branca que havia sido adicionada sob o logotipo da capa escura.
- Desenvolvidos exemplos internos nos três capítulos do template:
  - tabelas pequena, média e grande;
  - equações pequena, média e grande em múltiplas linhas;
  - gráfico individual, dois gráficos lado a lado e quatro gráficos em matriz 2 x 2;
  - fotografia centralizada e fotografia com texto lateral;
  - blocos em duas, três e quatro colunas;
  - exemplo de três parágrafos contínuos.
- Adicionado asset de fotografia placeholder em `assets/figures/versatus-photo-placeholder.png`.
- Adicionados pacotes editoriais para exemplos visuais: `pgfplots`, `subcaption`, `wrapfig`, `multicol` e `float`.
- Ajustado contraste dos títulos em blocos técnicos `VSNote` e `VSWarning`.

## v0.2.1

- Marca d'água interna ampliada.
- Capas sem marca d'água decorativa no canto inferior direito.
- Capas coloridas com logotipo horizontal colorido da Versatus HPC.
- Símbolo no rodapé ampliado.
- Rodapé com contador `Página X de Y` usando o total absoluto de páginas do PDF.

## v0.2.0

- Refatoração para arquitetura com múltiplos arquivos-raiz.
- Inclusão das variantes `standard`, `print`, `longread` e `longread-mono`.
- Inclusão do fundo warm profissional `#FCFAF2`.
- Separação do núcleo visual em arquivos `.sty`.
- Inclusão de duas opções de capa TikZ: A e B.
- Rodapé com símbolo Versatus em versão colorida ou monocromática.
- Marca d'água discreta com logotipo monocromático.
- Scripts de build para Linux/macOS e Windows PowerShell.
- Documentação geral dos templates Versatus HPC.
