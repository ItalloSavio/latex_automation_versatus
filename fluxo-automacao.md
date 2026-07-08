# Fluxo de Automação — Intelligent Cover Compiler

Documentação do sistema de automação de capas para o template LaTeX `versatus-template-book`.  
Última atualização: julho de 2026.

---

## Visão Geral

O sistema recebe uma **imagem de referência** e o nome de uma **marca** e produz:

- Fundo geométrico extraído da imagem, com cores exatas da marca
- Logo da marca selecionado automaticamente pelo tom do fundo
- Tipografia, cores e identidade visual da marca aplicadas a todo o documento (sumário, títulos, rodapé, marca d'água)
- PDF da capa standalone + PDF do livro completo, em um único comando

```bash
# Capa + livro completo em um comando
python automation/scripts/build_cover.py <imagem.png> --brand <marca> --full-build
```

---

## Fluxo Completo

```
imagem.png  +  brands/<marca>/brand.json
       │
       ▼
[Fase 1 — Gemini Vision API]
  Prompt com regras de marca e formato TikZ
       │
       ▼  resposta bruta em TikZ → salva em canvas_last.tikz
[Enforcement determinístico de cores]
  Python substitui todo hex pelo valor exato do brand.json
       │
       ▼
[Seleção de logo por luminância WCAG]
  bg_primary → L < 0.35: dark / L > 0.60: light / meio: alt
  Logo .tikz pré-convertido embutido inline no .tex
       │
       ▼
[Geração do preâmbulo de marca]
  \setmainfont{<fonte>}
  \definecolor{VS*}{...}            ← cores do documento inteiro
  \renewcommand{\VSBrandFooterLogo} ← logo no rodapé de todas as páginas
  \renewcommand{\VSBrandWatermark}  ← marca d'água de todas as páginas
       │
       ▼  styles/versatus-dynamic-cover.tex  (gerado)
[Fase 2 — LuaLaTeX]
  main-dynamic.tex (capa standalone)
       │
       ▼
[Fase 3 — Preview PNG]
  Renderiza página 1 do PDF → cover_preview.png
  Abre automaticamente no visualizador padrão
       │
       ▼  (opcional: --refine)
[Fase 4 — Refinamento VLM]
  Envia imagem original + PNG gerado ao Gemini
  Gemini compara e corrige o TikZ
  Recompila + atualiza preview
       │
       ▼  (opcional: --full-build)
[Fase 5 — Livro Completo]
  Compila main.tex com capa + conteúdo + identidade visual da marca
```

---

## Comandos

### Pipeline completo

```bash
# Fluxo básico: imagem + marca → PDF da capa
python automation/scripts/build_cover.py capa.png --brand versatus

# Gerar capa E livro completo de uma vez
python automation/scripts/build_cover.py capa.png --brand versatus --full-build

# Com refinamento automático (1 passagem de correção)
python automation/scripts/build_cover.py capa.png --brand kosen --refine

# Com refinamento + livro completo
python automation/scripts/build_cover.py capa.png --brand kosen --refine --full-build
```

### Reusar TikZ existente (sem chamar a API)

```bash
# Reaplicar marca sobre o último TikZ gerado (canvas_last.tikz)
# Útil para testar a mesma capa com marcas diferentes
python automation/scripts/build_cover.py --reuse --brand versatus
python automation/scripts/build_cover.py --reuse --brand kosen

# Reusar + compilar livro completo
python automation/scripts/build_cover.py --reuse --brand kosen --full-build

# Reusar o .tex já gerado sem reaplicar brand (modo legado/debug)
python automation/scripts/build_cover.py --skip-vision
```

### Opções de refinamento

```bash
# Uma passagem de refinamento (padrão quando --refine é usado)
python automation/scripts/build_cover.py capa.png --brand versatus --refine

# Duas passagens de refinamento (máximo recomendado: 3)
python automation/scripts/build_cover.py capa.png --brand versatus --refine --refine-passes 2
```

O `--refine` funciona assim:
1. Compila a capa normalmente e gera o preview PNG
2. Envia ao Gemini: imagem original + PNG do resultado atual
3. O Gemini compara visualmente e retorna um `\RenderDynamicCover` corrigido
4. Recompila e atualiza o preview
5. Com `--refine-passes 2`, repete os passos 2–4

### Preview

```bash
# Gerar preview em alta resolução (padrão: 150 dpi)
python automation/scripts/build_cover.py --reuse --brand versatus --dpi 300

# Gerar preview sem abrir automaticamente
python automation/scripts/build_cover.py capa.png --brand versatus --no-preview
```

### Logos

```bash
# Converter logos SVG → TikZ de uma marca
python automation/scripts/convert_logos.py --brand versatus
python automation/scripts/convert_logos.py --brand kosen

# Converter todas as marcas de uma vez
python automation/scripts/convert_logos.py --all

# Altura customizada (default: valor de logo_height_cm no brand.json, ou 3 cm)
python automation/scripts/convert_logos.py --brand versatus --height 2.5

# Converter SVG individual (uso avulso)
python automation/scripts/svg_to_tikz.py brands/versatus/logos/svg/logo_dark.svg LogoVersatusDark --height 3
```

### Configuração via `pipeline.toml`

Em vez de passar as flags em todo comando, edite `automation/pipeline.toml`:

```toml
[pipeline]
brand = "versatus"           # --brand
main  = "main-dynamic.tex"  # --main

[compile]
dpi        = 150    # --dpi
full_build = false  # --full-build
no_preview = false  # --no-preview

[refine]
enabled = false  # --refine
passes  = 1      # --refine-passes
```

CLI flags sempre têm prioridade sobre o arquivo. O arquivo é carregado automaticamente se existir — nenhum flag adicional necessário.

```bash
# Com pipeline.toml configurado (brand="kosen", full_build=true):
python automation/scripts/build_cover.py capa.png   # equivale a --brand kosen --full-build
python automation/scripts/build_cover.py --reuse    # equivale a --reuse --brand kosen --full-build

# Sobrescrever o brand do toml na linha de comando:
python automation/scripts/build_cover.py capa.png --brand versatus
```

### Variáveis de ambiente

| Variável         | Obrigatória | Descrição                                                                                     |
|------------------|-------------|-----------------------------------------------------------------------------------------------|
| `GEMINI_API_KEY` | Sim         | Chave da API Google AI Studio                                                                 |
| `GEMINI_MODEL`   | Não         | Forçar modelo específico (ex: `gemini-2.0-flash`). Se omitido, usa cadeia automática de fallback. |

```bash
# Windows (PowerShell)
$env:GEMINI_API_KEY = "sua_chave_aqui"
python automation/scripts/build_cover.py capa.png --brand versatus
```

---

## Arquivos do Sistema

### Estrutura de pastas

```
versatus-template-book-v0.2.3/
│
├── automation/
│   ├── pipeline.toml               # Configuração de defaults (brand, dpi, etc.)
│   ├── core/
│   │   └── latex_compiler.py       # Compilador LuaLaTeX com auto-repair
│   ├── prompt/
│   │   ├── vision_prompt.txt       # Prompt principal do Gemini Vision
│   │   └── refine_header.txt       # Prefixo do prompt de refinamento
│   ├── output/
│   │   ├── canvas_last.tikz        # Última resposta bruta do Gemini (debug/reuse)
│   │   └── cover_preview.png       # Preview PNG da última compilação
│   └── scripts/
│       ├── build_cover.py          # PONTO DE ENTRADA principal
│       ├── vision_extractor.py     # Gemini Vision → TikZ (com brand support)
│       ├── preview_cover.py        # PDF → PNG (usa pymupdf)
│       ├── convert_logos.py        # Batch conversion SVG→TikZ por marca
│       └── svg_to_tikz.py          # Conversor SVG→TikZ puro Python
│
├── tests/
│   └── test_vision_extractor.py    # 84 testes unitários (sem API, sem LaTeX)
│
├── brands/
│   ├── versatus/
│   │   ├── brand.json              # Identidade visual: cores, fonte, logos
│   │   └── logos/
│   │       ├── svg/                # Logos originais em SVG (fornecidos pela marca)
│   │       │   ├── logo_dark.svg
│   │       │   ├── logo_light.svg
│   │       │   └── logo_simbol.svg
│   │       ├── logo_dark.tikz      # Logo convertido (gerado por convert_logos.py)
│   │       ├── logo_light.tikz
│   │       └── logo_simbol.tikz
│   └── kosen/
│       └── ...                     # Mesma estrutura
│
├── styles/
│   ├── versatus-dynamic-cover.tex  # GERADO AUTOMATICAMENTE — não editar
│   ├── versatus-covers.sty         # Layouts de capa (estático)
│   ├── versatus-colors.sty         # Paleta Versatus base (sobrescrita pelo brand preamble)
│   ├── versatus-layout.sty         # Layout de páginas, cabeçalho/rodapé, títulos
│   ├── versatus-typography.sty     # Tipografia base (sobrescrita pelo brand preamble)
│   └── versatus-variant.sty        # Flags de variante (color/print/longread)
│
├── frontmatter/
│   ├── cover.tex                   # Usa capa dinâmica se disponível, fallback para estática
│   └── toc.tex
│
├── main.tex                        # Livro completo (capas + conteúdo + layout da marca)
├── main-dynamic.tex                # Capa standalone (preview rápido durante iteração)
├── config/metadata.tex             # Título, autor, data, versão
└── build/
    ├── pdf/main-dynamic.pdf        # PDF da capa (gerado pelo pipeline)
    ├── pdf/main.pdf                # PDF do livro completo (gerado com --full-build)
    └── aux/                        # Arquivos auxiliares LaTeX (.log, .aux, .toc...)
```

---

## Arquivo `brand.json`

Cada marca tem um `brand.json` em `brands/<nome>/brand.json`:

```json
{
  "company": "Nome da Empresa",
  "font": "Source Sans Pro",
  "colors": {
    "bg_primary":   "#201F1E",
    "bg_secondary": "#2B2928",
    "accent_1":     "#4CB6B4",
    "accent_2":     "#DD4F51",
    "neutral":      "#BCB9B9",
    "light":        "#FFFFFF",
    "muted":        "#5D5956"
  },
  "logos": {
    "dark":  "logos/logo_dark.tikz",
    "light": "logos/logo_light.tikz",
    "alt":   "logos/logo_simbol.tikz"
  },
  "logo_svg": {
    "dark":  "logos/svg/logo_dark.svg",
    "light": "logos/svg/logo_light.svg",
    "alt":   "logos/svg/logo_simbol.svg"
  },
  "logo_height_cm": 1.5,
  "logo_position": [1.5, 26.5]
}
```

### Papéis das cores

| Papel          | Uso no documento                                                                 |
|----------------|----------------------------------------------------------------------------------|
| `bg_primary`   | Cor dominante/escura do fundo; define o tom para seleção do logo e títulos (`VSBlack`) |
| `bg_secondary` | Segunda cor de fundo (zonas secundárias)                                         |
| `accent_1`     | Acento principal (ex: teal da Versatus); usado em links externos (`VSTeal`)      |
| `accent_2`     | Acento secundário (ex: vermelho da Versatus); linha separadora, links de capítulo |
| `neutral`      | Zona neutra/cinza                                                                |
| `light`        | Branco ou claro (base e fundos claros)                                           |
| `muted`        | Cinza muted (texto secundário, rodapés)                                          |

### Variantes de logo

| Chave   | Convenção                                                   |
|---------|-------------------------------------------------------------|
| `dark`  | Logo para **fundos escuros** — cores claras/brancas no logo |
| `light` | Logo para **fundos claros** — cores escuras no logo         |
| `alt`   | Símbolo/ícone isolado — para fundos médios ou uso compacto  |

A capa usa a variante escolhida pela luminância do fundo. O rodapé sempre usa `alt` (símbolo). A marca d'água usa `dark`.

### Campos opcionais de layout

| Campo            | Tipo          | Default       | Descrição                                              |
|------------------|---------------|---------------|--------------------------------------------------------|
| `logo_position`  | `[x, y]` (cm) | `[1.5, 26.5]` | Fallback de posição (sobrescrito pelo LOGO_PLACEMENT do VLM) |
| `logo_height_cm` | número        | `3.0`         | Altura alvo na conversão SVG→TikZ                      |

---

## Como Adicionar uma Nova Marca

1. **Criar a pasta e o `brand.json`:**
   ```
   brands/nova-marca/brand.json
   ```

2. **Colocar os SVGs:**
   ```
   brands/nova-marca/logos/svg/logo_dark.svg
   brands/nova-marca/logos/svg/logo_light.svg
   brands/nova-marca/logos/svg/logo_simbol.svg
   ```

3. **Converter logos para TikZ:**
   ```bash
   python automation/scripts/convert_logos.py --brand nova-marca
   ```

4. **Gerar capa e livro:**
   ```bash
   python automation/scripts/build_cover.py capa.png --brand nova-marca --full-build
   ```

---

## Detalhes Técnicos

### Por que não usamos svg2tikz ou Inkscape?

`svg2tikz` depende de `pygobject` (GTK), que exige toolchain nativo para compilar no Windows. Inkscape também não estava disponível como dependência confiável.

A solução foi escrever `svg_to_tikz.py` usando apenas `svgelements` (`pip install svgelements` — puro Python, sem compilação nativa), funcionando em qualquer máquina com Python + pip.

### Validação pré-compilação

Antes de chamar o LuaLaTeX, `_validate_tikz` checa o bloco gerado pelo VLM e emite avisos imediatos (sem esperar 30s de compilação) para:

| Checagem | O que detecta |
|---|---|
| `\begin/\end{tikzpicture}` presentes | Bloco estruturalmente inválido |
| `% LOGO_PLACEMENT` presente | Se ausente, logo vai para posição padrão, ignorando a imagem |
| `bg=ROLE` corresponde a um `\definecolor` declarado | `bg=dark` em vez de `bg=bg_primary` causaria logo com variante errada |
| 6 macros obrigatórias presentes (`\BookTitle`, `\BookSubtitle`, `\BookDescription`, `\BookAuthor`, `\BookDate`, `\BookVersion`) | VLM omitiu conteúdo — capa compila mas sem texto |
| Números > 150 (suspeito de pixels em vez de cm) | Coordenadas em pixels causam geometria fora da página |

### Enforcement determinístico de cores

O Gemini não consegue garantir um hexadecimal exato — pode "alucinar" valores próximos mas errados. A solução: o VLM recebe instruções para usar **nomes de papéis semânticos** (`bg_primary`, `accent_1`, etc.) e o Python substitui deterministicamente **cada `\definecolor` pelo hex exato** do `brand.json`, via regex. O VLM decide a composição; o Python garante os valores exatos.

### Seleção de logo por luminância (WCAG)

Algoritmo sobre o hex do fundo onde o logo será colocado (detectado do comentário `LOGO_PLACEMENT` do VLM):

- `L < 0.35` → fundo **escuro** → variante `dark`
- `L > 0.60` → fundo **claro** → variante `light`
- `0.35 ≤ L ≤ 0.60` → fundo **médio** → variante `alt`

A variante escolhida é **embutida inline** no `versatus-dynamic-cover.tex` para evitar problemas de caminho relativo.

### Integração com o documento completo

`versatus-dynamic-cover.tex` é carregado no **preâmbulo** de `main.tex` (via `\IfFileExists`), o que propaga a identidade visual da marca para todo o documento:

| O que muda                    | Como                                                                      |
|-------------------------------|---------------------------------------------------------------------------|
| Fonte do documento            | `\setmainfont{<fonte>}` no preâmbulo                                      |
| Cores de títulos/links/regras | `\definecolor{VSBlack/VSRed/VSTeal...}` sobrescreve `versatus-colors.sty` |
| Logo no rodapé                | `\renewcommand{\VSBrandFooterLogo}` — logo alt 0,5 cm de altura           |
| Marca d'água                  | `\renewcommand{\VSBrandWatermark}` — logo dark 12 cm, 3% opacidade        |
| Capa dinâmica                 | `\VSBookCoverDynamic` renderiza `\RenderDynamicCover`                     |

Quando o pipeline **não foi rodado** (primeiro compile), `\IfFileExists` não encontra o arquivo e o documento compila normalmente com a identidade visual padrão da Versatus.

### Fallback automático de contraste (VSRed / links)

`VSRed` é usado como `linkcolor` em todo o documento. Em marcas onde `accent_2` tem contraste insuficiente com `bg_primary` (ratio WCAG < 2,5), o sistema substitui por `muted` (cinza médio, ~4,7:1 de contraste no papel branco) em vez de `light` (que seria branco sobre branco).

Exemplo Kosen: `accent_2 = #3B3CD0` vs `bg_primary = #4038FF` → ratio ≈ 1,19 → substituição por `muted = #757576`.

### Mapeamento brand.json → cores LaTeX

| Cor LaTeX        | Papel no `brand.json` | Uso no documento                          |
|------------------|-----------------------|-------------------------------------------|
| `VSBlack`        | `bg_primary`          | Títulos de capítulo/seção, texto primário |
| `VSGraphite`     | `bg_secondary`        | Subtítulos, elementos secundários         |
| `VSTeal`         | `accent_1`            | Links externos, destaques                 |
| `VSRed`          | `accent_2`            | Links de capítulo, separadores na capa    |
| `VSSilver`       | `neutral`             | Decorações neutras                        |
| `VSPaperWhite`   | `light`               | Fundo do papel, zonas claras              |
| `VSMutedText`    | `muted`               | Texto de rodapé, anotações                |

### Estrutura do arquivo gerado (`versatus-dynamic-cover.tex`)

```
% Cabeçalho com metadados (gerado automaticamente — não editar)
% === Brand preamble: <Empresa> ===
\IfFontExistsTF{<fonte>}{ \setmainfont{...} }{ fallback Noto Sans / LM Sans }
\definecolor{VSBlack}{HTML}{...}
... (demais cores VS*)
\definecolor{VSCoverFg}{HTML}{...}     ← cor de texto na capa (adapta ao fundo)
% === end brand preamble ===

\newcommand{\Logo<Marca><VarianteCapa>}[1]{ ... }    ← logo da capa (inline)
\newcommand{\Logo<Marca><VarianteRodapé>}[1]{ ... }  ← logo alt para rodapé (inline, se diferente)
\newcommand{\Logo<Marca><VarianteMarca>}[1]{ ... }   ← logo dark para marca d'água (inline, se diferente)

\renewcommand{\VSBrandFooterLogo}{%
  \resizebox{!}{0.50cm}{\begin{tikzpicture}...\Logo<Marca>Alt{(0,0)}...\end{tikzpicture}}
}
\renewcommand{\VSBrandWatermark}{%
  \ifVSWatermark
  \begin{tikzpicture}[remember picture, overlay]
    \node[opacity=0.030, ...] {\resizebox{12cm}{!}{...\Logo<Marca>Dark{(0,0)}...}};
  \end{tikzpicture}%
  \fi
}

\newcommand{\RenderDynamicCover}{%
  \definecolor{bg_primary}{HTML}{...}
  ... (cores dos papéis semânticos)
  \begin{tikzpicture}[...]
    ... (geometria extraída da imagem de referência)
    % LOGO_PLACEMENT x=X y=Y height=H bg=ROLE
    \Logo<Marca><Variante>{(x, y)}   ← logo posicionado pelo VLM
  \end{tikzpicture}%
}
```

---

## Marcas Configuradas

### Versatus HPC

| Campo          | Valor                   |
|----------------|-------------------------|
| Fonte          | Source Sans Pro         |
| `bg_primary`   | `#201F1E` (charcoal)    |
| `bg_secondary` | `#2B2928` (grafite)     |
| `accent_1`     | `#4CB6B4` (teal)        |
| `accent_2`     | `#DD4F51` (vermelho)    |
| `neutral`      | `#BCB9B9` (prata)       |
| `light`        | `#FFFFFF` (branco)      |
| `muted`        | `#5D5956` (cinza muted) |

### Kosen Energy

| Campo            | Valor                                        |
|------------------|----------------------------------------------|
| Fonte            | Work Sans                                    |
| `bg_primary`     | `#4038FF` (azul)                             |
| `bg_secondary`   | `#C7B99C` (bege)                             |
| `accent_1`       | `#C7B99C` (bege)                             |
| `accent_2`       | `#3B3CD0` (azul escuro)                      |
| `neutral`        | `#C6C6C8` (cinza claro)                      |
| `light`          | `#FFFFFF` (branco)                           |
| `muted`          | `#757576` (cinza)                            |
| `logo_height_cm` | `1.5`                                        |
| `logo_position`  | `[1.5, 27.0]`                                |

> `VSRed` usa fallback para `muted = #757576` (cinza): `accent_2 #3B3CD0` tem ratio 1,19 com `bg_primary #4038FF` — ambos azuis similares.

---

## Outputs Gerados

| Arquivo                              | Quando é gerado                      | Pode deletar? |
|--------------------------------------|--------------------------------------|---------------|
| `styles/versatus-dynamic-cover.tex`  | A cada execução do pipeline          | Sim — regenerado automaticamente |
| `build/pdf/main-dynamic.pdf`         | A cada compilação da capa            | Sim           |
| `build/pdf/main.pdf`                 | Quando `--full-build` é usado        | Sim           |
| `build/aux/`                         | A cada compilação                    | Sim           |
| `automation/output/canvas_last.tikz` | A cada chamada ao Gemini             | Sim (usado por `--reuse`) |
| `automation/output/cover_preview.png`| A cada compilação (Fase 3)           | Sim           |
| `brands/<marca>/logos/*.tikz`        | Por `convert_logos.py`               | Não — necessários para o pipeline |

---

## Requisitos

### Python
```bash
pip install google-genai svgelements pymupdf

# Para rodar os testes unitários:
pip install pytest
pytest tests/ -v
```

| Pacote         | Uso                                                        |
|----------------|------------------------------------------------------------|
| `google-genai` | Chamadas ao Gemini Vision (Fase 1 e 4)                     |
| `svgelements`  | Conversão SVG→TikZ (puro Python, sem GTK)                  |
| `pymupdf`      | Renderização PDF→PNG para preview (Fase 3)                 |
| `pytest`       | Testes unitários (opcional — não necessário para o pipeline)|

### LaTeX
- LuaLaTeX (via MiKTeX ou TeX Live)
- `latexmk`
- Pacotes: `fontspec`, `tikz`, `xcolor`, `etoolbox`, `microtype`, `babel`, `tocloft`, `titlesec`, `eso-pic`, `zref`

### Fontes
As fontes das marcas precisam estar instaladas no sistema operacional. Se não estiverem, o sistema faz fallback automático: `Noto Sans` → `Latin Modern Sans`. O PDF compila normalmente em qualquer caso.
