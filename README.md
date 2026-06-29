# Versatus HPC Book Template v0.2.3

Template LaTeX corporativo para livros técnicos, programas de estudo e materiais didáticos da Versatus HPC.

## Variantes incluídas

| Arquivo-raiz | Uso | Fundo | Capa | Rodapé |
|---|---|---:|---|---|
| `main-standard.tex` | versão editorial padrão | branco | colorida | símbolo colorido |
| `main-print.tex` | versão de impressão | branco | monocromática | símbolo preto |
| `main-longread.tex` | leitura prolongada | warm `#FCFAF2` | colorida | símbolo colorido |
| `main-longread-mono.tex` | leitura prolongada sem cor | warm `#FCFAF2` | monocromática | símbolo preto |

O arquivo `main.tex` contém a estrutura real do documento. Os quatro arquivos-raiz acima apenas definem a variante e chamam `main.tex`.

## Compilação rápida

Requer LuaLaTeX e `latexmk`.

Linux/macOS:

```bash
./build-all.sh
```

Windows PowerShell:

```powershell
.\build-all.ps1
```

Ou por variante:

```bash
latexmk -lualatex main-standard.tex
latexmk -lualatex main-print.tex
latexmk -lualatex main-longread.tex
latexmk -lualatex main-longread-mono.tex
```

Com `make`:

```bash
make all
make standard
make print
make longread
make longread-mono
```

## Onde editar

Edite os metadados em:

```text
config/metadata.tex
```

Edite ou adicione capítulos em:

```text
chapters/
```

Altere a capa em cada arquivo-raiz com:

```tex
\def\VSCoverOption{A}
```

ou:

```tex
\def\VSCoverOption{B}
```

## Estrutura

```text
assets/logos/          logotipos e símbolos oficiais
assets/figures/        imagens placeholder para exemplos internos
backmatter/            glossário e índice
build/                 diretório de saída dos PDFs
chapters/              capítulos do livro
config/                metadados do documento
covers/                área reservada para futuras capas autônomas
docs/                  documentação do template
frontmatter/           capa e sumário
styles/                núcleo visual e editorial Versatus HPC
main*.tex              arquivos-raiz de compilação
```

## Observações de marca

O template usa Source Sans Pro quando instalada. Se ela não existir no sistema, usa Source Sans 3, Noto Sans, TeX Gyre Heros ou Latin Modern Sans como fallback. Os arquivos de fonte não são distribuídos no template.

As cores oficiais usadas no template são: `#4CB6B4`, `#BCB9B9`, `#DD4F51` e `#201F1E`.

## Alterações visuais desta versão

- Marca d’água interna ampliada.
- Capas sem marca d’água decorativa no canto inferior direito.
- Capa colorida escura com a versão correta do logotipo para fundo escuro.
- Capas sem marca d’água decorativa no canto inferior direito.
- Marca d’água interna ampliada.
- Símbolo no rodapé ampliado.
- Rodapé com contador `Página X de Y`.
- Capítulos internos desenvolvidos com exemplos de tabelas, equações, gráficos, fotos e blocos multicoluna.


## Blocos de código e teoremas

A versão v0.2.3 inclui exemplos adicionais de composição interna para livros técnicos: blocos de código em estilo terminal, blocos de código em fundo claro, teoremas, lemas, corolários, provas e três tipos de blocos de destaque. A implementação usa `listings` com `tcolorbox`, sem dependência de `minted`, `shell-escape` ou Pygments.
