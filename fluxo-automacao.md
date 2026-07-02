# Fluxo de Automação — Intelligent Cover Compiler

Documentação do sistema de automação de capas para o template LaTeX `versatus-template-book`.  
Última atualização: julho de 2026.

---

## Visão Geral

O sistema recebe uma **imagem de referência** e o nome de uma **marca** e produz um **PDF completo** com:

- Fundo geométrico extraído da imagem de referência, com cores exatas da marca
- Logo da marca selecionado automaticamente pelo tom do fundo
- Tipografia e cores do documento alinhadas à identidade visual da marca

Tudo em um único comando, sem dependências de sistema além do Python e do LaTeX.

```
python automation/scripts/build_cover.py <imagem.png> --brand <marca>
```

---

## Fluxo Completo

```
imagem.png  +  brands/<marca>/brand.json
       │
       ▼
[Fase 1 — Gemini Vision API]
  Prompt com instrução de cores da marca
       │
       ▼  resposta em TikZ
[Enforcement determinístico de cores]
  Python substitui todo hex pelo valor exato do brand.json
       │
       ▼
[Seleção de logo por luminância]
  bg_primary → WCAG luminance → dark / light / alt
  Logo .tikz pré-convertido é embutido inline
       │
       ▼
[Geração do preâmbulo de marca]
  \setmainfont{<fonte>} + \definecolor{VS*}{...}
       │
       ▼  styles/versatus-dynamic-cover.tex  (gerado)
[Fase 2 — LuaLaTeX + latexmk]
       │
       ▼
  build/pdf/main-dynamic.pdf
```

---

## Comandos

### Pipeline principal

```bash
# Fluxo completo: imagem + marca → PDF
python automation/scripts/build_cover.py <imagem.png> --brand versatus

# Reusar TikZ existente (sem chamar o Gemini novamente)
python automation/scripts/build_cover.py <imagem.png> --brand versatus --skip-vision

# Sem marca (cores livres geradas pelo VLM)
python automation/scripts/build_cover.py <imagem.png>
```

### Logos

```bash
# Converter logos SVG → TikZ de uma marca
python automation/scripts/convert_logos.py --brand versatus
python automation/scripts/convert_logos.py --brand kosen

# Converter todas as marcas de uma vez
python automation/scripts/convert_logos.py --all

# Converter logo único com altura customizada (default: 3 cm)
python automation/scripts/convert_logos.py --brand versatus --height 2.5

# Converter SVG individual (uso avulso)
python automation/scripts/svg_to_tikz.py brands/versatus/logos/svg/logo_dark.svg LogoVersatusDark --height 3
```

### Variáveis de ambiente

| Variável        | Obrigatória | Descrição                                                   |
|-----------------|-------------|-------------------------------------------------------------|
| `GEMINI_API_KEY` | Sim         | Chave da API Google AI Studio                               |
| `GEMINI_MODEL`   | Não         | Forçar modelo específico (ex: `gemini-2.0-flash`). Se omitido, o sistema usa cadeia automática de fallback. |

```bash
# Windows
set GEMINI_API_KEY=sua_chave_aqui
python automation/scripts/build_cover.py capa.png --brand versatus
```

---

## Arquivos do Sistema

### Estrutura de pastas

```
versatus-template-book-v0.2.3/
│
├── automation/
│   ├── core/
│   │   ├── latex_compiler.py       # Compilador LuaLaTeX com auto-repair
│   │   └── json_to_tikz.py         # (legado) Conversor JSON→TikZ
│   ├── prompt/
│   │   ├── vision_prompt.txt       # Prompt do Gemini Vision (com {{COLOR_INSTRUCTIONS}})
│   │   └── repair_prompt.txt       # Prompt de reparo automático (modo legado)
│   ├── output/
│   │   ├── canvas_last.tikz        # Última resposta bruta do Gemini (debug)
│   │   └── canvas_last.json        # Último JSON de canvas (modo legado)
│   └── scripts/
│       ├── build_cover.py          # PONTO DE ENTRADA principal
│       ├── vision_extractor.py     # Gemini Vision → TikZ (com brand support)
│       ├── convert_logos.py        # Batch conversion SVG→TikZ por marca
│       └── svg_to_tikz.py          # Conversor SVG→TikZ puro Python
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
│   ├── versatus-typography.sty     # Tipografia base (sobrescrita pelo brand preamble)
│   └── versatus-variant.sty        # Flags de variante (color/print/longread)
│
├── main-dynamic.tex                # Entry-point LaTeX que inclui tudo
├── config/metadata.tex             # Título, autor, data, versão do documento
└── build/
    ├── pdf/main-dynamic.pdf        # PDF final gerado
    └── aux/main-dynamic.log        # Log de compilação LaTeX
```

---

## Arquivo `brand.json`

Cada marca tem um `brand.json` em `brands/<nome>/brand.json` com a seguinte estrutura:

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
  "logo_position": [1.5, 26.5],
  "text_panel": {
    "color":   "bg_primary",
    "opacity": 0.85,
    "x1": -1,  "y1": 4.5,
    "x2": 22,  "y2": 25.5
  }
}
```

### Papéis das cores

| Papel          | Uso no documento                                              |
|----------------|---------------------------------------------------------------|
| `bg_primary`   | Cor dominante/escura do fundo; define tom para seleção do logo |
| `bg_secondary` | Segunda cor de fundo (zonas secundárias)                      |
| `accent_1`     | Acento principal (ex: teal da Versatus)                       |
| `accent_2`     | Acento secundário (ex: vermelho da Versatus); usado na linha separadora do texto |
| `neutral`      | Zona neutra/cinza                                             |
| `light`        | Branco ou claro (base e fundos claros)                        |
| `muted`        | Cinza muted (texto secundário, rodapés)                       |

### Variantes de logo

| Chave   | Convenção                                                  |
|---------|------------------------------------------------------------|
| `dark`  | Logo para **fundos escuros** — cores claras/brancas no logo |
| `light` | Logo para **fundos claros** — cores escuras no logo         |
| `alt`   | Símbolo/ícone isolado — para fundos médios ou uso compacto  |

### Campos opcionais de layout

| Campo             | Tipo           | Default       | Descrição                                                  |
|-------------------|----------------|---------------|------------------------------------------------------------|
| `logo_position`   | `[x, y]` (cm) | `[1.5, 26.5]` | Canto inferior esquerdo do logo. Origem = canto inf. esq. da página (A4: 21×29,7 cm). |
| `logo_height_cm`  | número         | `3.0`         | Altura alvo na conversão SVG→TikZ. Controla o tamanho do logo na capa. |
| `text_panel`      | objeto         | —             | Retângulo de fundo para a zona de texto. Ver tabela abaixo. |

#### Campos de `text_panel`

| Campo     | Tipo   | Descrição                                                    |
|-----------|--------|--------------------------------------------------------------|
| `color`   | string | Nome de cor (papel do brand.json, ex: `"bg_primary"`)        |
| `opacity` | float  | Opacidade do preenchimento, 0.0–1.0 (ex: `0.85`)            |
| `x1`,`y1` | números| Canto inferior esquerdo do retângulo, em cm                  |
| `x2`,`y2` | números| Canto superior direito do retângulo, em cm                   |

> **Quando usar `text_panel`:** quando o background geométrico gerado pelo VLM é muito denso na área de texto (ex: padrões full-bleed), um painel semi-transparente cria zona de leitura clara sem perder a textura visual do fundo.

---

## Como Adicionar uma Nova Marca

1. **Criar a pasta e o `brand.json`:**
   ```
   brands/nova-marca/brand.json
   ```
   Seguindo a estrutura acima com todos os hexadecimais válidos (`#RRGGBB`).

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

4. **Usar na automação:**
   ```bash
   python automation/scripts/build_cover.py capa.png --brand nova-marca
   ```

---

## Detalhes Técnicos

### Por que não usamos svg2tikz ou Inkscape?

`svg2tikz` depende de `pygobject` (GTK), que exige toolchain nativo para compilar no Windows — instalação instável e diferente máquina a máquina. Inkscape também não estava disponível.

A solução foi escrever `svg_to_tikz.py` usando apenas `svgelements` (`pip install svgelements` — puro Python, sem compilação nativa), tornando o sistema funcional em qualquer máquina com Python + pip.

### Enforcement determinístico de cores

O Gemini não consegue garantir que vai gerar um hexadecimal exato — ele pode "alucinar" valores próximos mas errados. A solução: o VLM recebe instruções para usar **nomes de papéis semânticos** (`bg_primary`, `accent_1`, etc.) e escolher qual papel vai em cada zona visual. Depois, o Python substitui deterministicamente **cada `\definecolor` pelo hex exato** do `brand.json`, via regex, sem nenhuma chamada de rede adicional. O VLM faz a escolha de composição; o Python garante os valores exatos.

### Seleção de logo por luminância (WCAG)

O algoritmo usa a fórmula de luminância relativa do WCAG 2.1 sobre `bg_primary`:

- `L < 0.35` → fundo **escuro** → variante `dark` (logo com cores claras)
- `L > 0.60` → fundo **claro** → variante `light` (logo com cores escuras)
- `0.35 ≤ L ≤ 0.60` → fundo **médio** → variante `alt` (símbolo/ícone)

A variante escolhida é **embutida inline** no `versatus-dynamic-cover.tex` (não via `\input`) para evitar problemas de caminho relativo quando o LaTeX processa o arquivo.

### Preâmbulo de marca no LaTeX

`versatus-dynamic-cover.tex` é carregado no **preâmbulo** do `main-dynamic.tex` (antes do `\begin{document}`), o que permite:

1. `\setmainfont{<fonte>}` com cadeia de fallback — fonte da marca sem travar se não instalada
2. `\definecolor{VSBlack}{HTML}{...}` etc. — sobrescreve as cores `VS*` definidas em `versatus-colors.sty` com os valores exatos da marca ativa

Isso significa que `versatus-covers.sty` (que usa `VSBlack`, `VSRed`, `VSMutedText` etc. no overlay de texto) herda automaticamente as cores da marca — **sem nenhuma modificação nos `.sty` existentes**.

### Fallback automático de contraste (separador VSRed)

O separador horizontal no overlay de texto usa a cor `VSRed` (= `accent_2`). Em marcas onde `accent_2` tem contraste insuficiente com `bg_primary` (ratio WCAG < 2,5), o sistema substitui automaticamente `VSRed` pela cor `light` da marca (geralmente branco), garantindo visibilidade sem intervenção manual.

Exemplo Kosen: `accent_2 = #3B3CD0` vs `bg_primary = #4038FF` → ratio ≈ 1,19 → troca automática por `light = #FFFFFF`.

### Mapeamento brand.json → cores LaTeX

| Cor LaTeX (`versatus-covers.sty`) | Papel no `brand.json` |
|-----------------------------------|-----------------------|
| `VSBlack`                         | `bg_primary`          |
| `VSGraphite`                      | `bg_secondary`        |
| `VSTeal`                          | `accent_1`            |
| `VSRed`                           | `accent_2`            |
| `VSSilver`                        | `neutral`             |
| `VSPaperWhite`                    | `light`               |
| `VSMutedText`                     | `muted`               |

### Estrutura do arquivo gerado (`versatus-dynamic-cover.tex`)

```
% cabeçalho (gerado automaticamente)
% === Brand preamble ===
\IfFontExistsTF{<fonte>}{ \setmainfont{...} }{ fallback... }
\definecolor{VSBlack}{HTML}{...}
... (demais cores VS*)
% === end brand preamble ===

\newcommand{\Logo<Marca><Variante>}[1]{ ... }   ← logo inlinado

\newcommand{\RenderDynamicCover}{%
  \definecolor{bg_primary}{HTML}{...}
  ... (cores dos papéis semânticos)
  \begin{tikzpicture}[...]
    ... (geometria extraída da imagem de referência)
    \Logo<Marca><Variante>{(x, y)}               ← chamada do logo
  \end{tikzpicture}%
}
```

---

## Marcas Configuradas

### Versatus HPC

| Campo          | Valor                  |
|----------------|------------------------|
| Fonte          | Source Sans Pro        |
| `bg_primary`   | `#201F1E` (charcoal)   |
| `bg_secondary` | `#2B2928` (grafite)    |
| `accent_1`     | `#4CB6B4` (teal)       |
| `accent_2`     | `#DD4F51` (vermelho)   |
| `neutral`      | `#BCB9B9` (prata)      |
| `light`        | `#FFFFFF` (branco)     |
| `muted`        | `#5D5956` (cinza muted)|

### Kosen Energy

| Campo             | Valor                                         |
|-------------------|-----------------------------------------------|
| Fonte             | Work Sans                                     |
| `bg_primary`      | `#4038FF` (azul)                              |
| `bg_secondary`    | `#C7B99C` (bege)                              |
| `accent_1`        | `#C7B99C` (bege)                              |
| `accent_2`        | `#3B3CD0` (azul escuro)                       |
| `neutral`         | `#C6C6C8` (cinza claro)                       |
| `light`           | `#FFFFFF` (branco)                            |
| `muted`           | `#757576` (cinza)                             |
| `logo_height_cm`  | `1.5` (logos convertidos a 1,5 cm de altura)  |
| `logo_position`   | `[1.5, 27.0]`                                 |
| `text_panel`      | `bg_primary, 85% opacity, y: 4,5→25,5`       |

> `VSRed` → fallback automático para `#FFFFFF` (branco): `accent_2 #3B3CD0` tem ratio 1,19 com `bg_primary #4038FF`.

---

## Outputs Gerados

| Arquivo                                  | Quando é gerado                  | Pode deletar? |
|------------------------------------------|----------------------------------|---------------|
| `styles/versatus-dynamic-cover.tex`      | A cada execução do pipeline      | Sim — regenerado automaticamente |
| `build/pdf/main-dynamic.pdf`             | A cada compilação LuaLaTeX       | Sim           |
| `build/aux/main-dynamic.log`             | A cada compilação                | Sim           |
| `automation/output/canvas_last.tikz`     | A cada chamada ao Gemini         | Sim (debug)   |
| `brands/<marca>/logos/*.tikz`            | Por `convert_logos.py`           | Não — necessários para o pipeline |

---

## Requisitos

### Python
```
pip install google-genai svgelements
```

### LaTeX
- LuaLaTeX (via MiKTeX ou TeX Live)
- `latexmk`
- Pacotes: `fontspec`, `tikz`, `xcolor`, `etoolbox`, `microtype`, `babel`

### Fontes
As fontes das marcas precisam estar instaladas no sistema operacional para serem usadas. Se não estiverem, o sistema faz fallback automático: `Noto Sans` → `Latin Modern Sans`. O PDF compila normalmente em qualquer caso.
