# PDF → LaTeX

Converte um PDF **digital** (exportado de navegador, Word ou InDesign — com texto de verdade)
em código LaTeX **editável**, compila de volta para PDF e mede o resultado contra o original.
PDF escaneado não serve: não tem texto, só imagem.

## As pastas

| pasta | o que tem |
|---|---|
| `entrada/` | os PDFs de origem (e as críticas de design) |
| `imagens/` | **onde você coloca** diagramas, logos e grafismos (ver "Imagens") |
| `saida/<nome>/` | o resultado de cada PDF convertido |
| `conversor/` | o código do conversor |

Dentro de `saida/<nome>/`:

| arquivo | o que é |
|---|---|
| `<nome>.tex` | **o conteúdo** — é aqui que se edita texto |
| `estilo.sty` | **o desenho** medido no original: fonte, escala tipográfica, cores, marcadores, cabeçalho |
| `diagramacao.sty` | a biblioteca de componentes (igual para todo documento; não precisa mexer) |
| `<nome>.pdf` | o PDF compilado |
| `espacos-de-imagem/` | `LISTA.md` com o nome e o tamanho de cada imagem a colocar, e um recorte do original |
| `comparacao/` | `relatorio.md` (original × gerado, em números) e imagens lado a lado e sobrepostas |

## Para só olhar o resultado

Não precisa instalar nada: o PDF gerado é
`saida/Versatus-HPC-Storage-Solution-Brief_v0.3/Versatus-HPC-Storage-Solution-Brief_v0.3.pdf`
e a comparação com o original está em `saida/Versatus-HPC-Storage-Solution-Brief_v0.3/comparacao/`
(`relatorio.md` e as imagens `lado-a-lado-p1..3.png`).

## Requisitos (para rodar)

- Python 3 com `pymupdf` e `numpy` (`pip install pymupdf numpy`); para `vetorizar_logo.py`,
  também `potracer` e `pillow`.
- LuaLaTeX (MiKTeX ou TeX Live) com os pacotes `sourcesanspro`, `fontspec`, `xcolor`, `graphicx`,
  `geometry` e `anyfontsize` — o MiKTeX instala sozinho os que faltarem.

## Os comandos (rodar da pasta que contém `pdf-para-latex/`)

```bash
# converter (gera o LaTeX, compila e compara)
python pdf-para-latex/conversor/pdf_para_latex.py pdf-para-latex/entrada/ARQUIVO.pdf

# depois de EDITAR o .tex ou o estilo.sty: só recompilar a sua versão
python pdf-para-latex/conversor/pdf_para_latex.py pdf-para-latex/entrada/ARQUIVO.pdf --so-compilar

# gerar de novo do zero, PERDENDO as edições feitas à mão
python pdf-para-latex/conversor/pdf_para_latex.py pdf-para-latex/entrada/ARQUIVO.pdf --sobrescrever
```

Se você editou o `.tex` e rodar o primeiro comando, o conversor **para e avisa** em vez de
sobrescrever.

## Editando

- **Texto:** no `.tex`, dentro de `\corpo{...}`, `\secao{...}`, `\item ...` etc. O texto flui
  dentro da coluna: as quebras de linha se refazem sozinhas.
- **`\quebra`** marca uma quebra de linha mantida só para ficar idêntico ao original (em títulos,
  e onde o original quebrou "por um fio"). Ao reescrever o trecho, pode apagar.
- **`\espaco{15}`** é a distância (em pontos) até o elemento anterior, medida no original.
- **`\entrelinha{12}`** antes de um bloco: aquele bloco usa outra entrelinha, porque o original
  usava.
- **Tamanhos, cores, fonte:** no `estilo.sty`. Cada `\definirestilo` é um degrau da escala
  tipográfica; mudar ali muda todas as ocorrências.
- **Colunas:** `\begin{coluna}{x}{y}{largura}` — posição do topo da coluna, em pontos, a partir
  do canto superior esquerdo da página. Se o texto crescer além do espaço, ele passa por cima
  do que estiver embaixo (como num programa de diagramação): encurte o texto ou mova a coluna.

## Imagens

Cada imagem, diagrama e grafismo do original virou um **espaço reservado com nome** (um retângulo
cinza com o nome e o tamanho). Para colocar a imagem:

1. veja o nome em `saida/<nome>/espacos-de-imagem/LISTA.md` (tem um recorte do original ao lado);
2. salve o arquivo com **esse nome** em `pdf-para-latex/imagens/` — `.pdf` para vetor (diagrama,
   logo), ou `.png`/`.jpg` a 300 dpi ou mais. SVG precisa ser exportado para PDF antes;
3. rode com `--so-compilar`.

A imagem é ajustada ao espaço sem distorcer. O grafismo da capa (`p1-grafismo-1`) é a parte
**visível** dele na página — o original sangra para fora da folha.

Se houver mais de um arquivo com o mesmo nome, vale nesta ordem: **`.pdf`**, `.png`, `.jpg`.
Na v0.3 a pasta tem os dois: os `.png` são os recortes do original; os `.pdf` são as versões em
alta qualidade, e são eles que entram:

| espaço | o que é o `.pdf` |
|---|---|
| `p1-imagem-1` | o logo Versatus — a imagem original embutida no PDF, em resolução cheia (573 × 196 px) |
| `p1-grafismo-1` | o grafismo da capa — **vetor**, recortado do PDF original |
| `p2-figura-1` | o diagrama — **vetor**, recortado do PDF original (os rótulos são texto de verdade) |
| `p3-imagem-1` | o logo da OpenSFS — **vetorizado** (`p3-imagem-1.svg` é o mesmo desenho), ver `conversor/vetorizar_logo.py` |

Para voltar a usar um `.png`, apague o `.pdf` de mesmo nome e rode `--so-compilar`.

## O que foi medido (Solution Brief v0.3)

195 de 195 linhas idênticas ao original (mesmo texto, mesma quebra); 95% das palavras a até
0,25 pt (0,09 mm) da posição original, nenhuma a mais de 0,7 pt. O relatório completo está em
`saida/Versatus-HPC-Storage-Solution-Brief_v0.3/comparacao/relatorio.md`.

## Limites conhecidos

- **Fonte:** o documento usa o pacote `sourcesanspro`, que hoje é um pacote de compatibilidade
  que carrega a **Source Sans 3** (a Adobe renomeou a família). O LaTeX avisa isso no log; é
  informativo. A SemiBold e a Itálica do MiKTeX são de uma versão um pouco diferente da embutida
  no PDF (larguras 0,3% e 1,3% diferentes) — por isso títulos guardam as quebras do original.
- **Tabelas** com fundo colorido nas células, célula que ocupa várias colunas, ou legenda dentro
  da tabela ainda não são reconhecidas (a v0.2 tem as três; a v0.3, nenhuma).
- **Bloco de texto recuado** fora de lista/chamada/faixa sai sem o recuo (o conversor avisa).
