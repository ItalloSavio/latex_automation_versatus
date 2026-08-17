# Swiss Cover Replicator — Revisão do Projeto

> Documento executivo. Estado atual, como funciona, como medimos e próximos passos.

---

## 1. O que é, em uma frase

Um sistema que **recria uma capa de design suíço como um PDF vetorial editável**,
automaticamente, a partir de uma imagem. Você envia um PNG da capa → o sistema
devolve um PDF (LaTeX/TikZ) visualmente igual — e **se corrige sozinho** até bater a
semelhança.

Não é "gerar uma capa parecida". É **reconstruir aquela capa específica**.

## 2. Por que essa abordagem importa

- **Determinístico** — mesma entrada produz sempre a mesma saída. A geração do código
  não usa IA generativa (que "alucina"); cada linha vem de uma medição.
- **Editável** — a saída é **vetorial** (texto, formas, cores como objetos), não uma
  imagem. Dá para ajustar qualquer elemento depois. Imprime em qualquer tamanho.
- **Autônomo** — o sistema mede o próprio resultado contra a original e corrige em
  loop, sem intervenção humana.

## 3. Como funciona (visão geral)

```
   IMAGEM
     │
     ▼
  [OCR]  lê o texto e ONDE ele está
     │
     ▼
  [Visão Computacional]  identifica cores, formas (retângulos, triângulos,
     │                   círculos), grade, e ONDE cada coisa fica ("mapa de layout")
     ▼
  [Gerador TikZ]  monta o PDF vetorial a partir dessas medições
     │
     ▼
  [Compara com a original]  → dá uma nota objetiva (Score)
     │
     ├── nota boa? → PRONTO
     └── nota ruim? → corrige e repete o loop
```

O diferencial é o **loop**: o sistema não tenta acertar de primeira — ele renderiza,
**mede a diferença** contra a original, corrige, e repete. E **só aceita uma correção
se a nota subiu** — então o resultado nunca piora.

## 4. Como medimos sucesso

Uma única nota, o **Score** (0 a 1), combina três medidas:

| Componente | O que mede | Peso |
|---|---|---|
| **content_match** | qualidade SÓ no conteúdo (ignora o fundo) | 50% |
| **SSIM** | similaridade estrutural geral | 30% |
| **content_iou** | se o conteúdo está no lugar certo | 20% |

**Por que não só SSIM (a métrica clássica)?** Porque ele **engana**: uma capa que é
75% fundo preto ganha nota alta só acertando o fundo, mesmo faltando todo o conteúdo.
Exemplo real: uma capa tinha SSIM 0.94 (parecia ótima) mas reproduzia só **3%** do
conteúdo. O `content_match` conta a verdade. **Meta: Score ≥ 0.95 = pronto.**

Ferramenta de inspeção visual (`review_board`): monta as 7 capas lado a lado
(original vs gerada + notas) para o olho humano validar — o juiz final.

## 5. Estado atual — 7 capas de teste

| Capa | Score | Situação |
|---|---|---|
| capa4 (david bowie) | **0.956** ✅ | **Pronta.** Referência — grade + triângulos + texto. |
| capa7 (Braun) | **0.874** ✅ | **Recém-destravada** — composição de círculos (+0.21 num único bug). |
| capa6 (rancid) | **0.926** ✅ | Quase pronta — grade + diagonais; falta só o texto miúdo. |
| capa3 (op-art) | **0.747** ↑ | Subiu de 0.60 — grade ciente-de-texto (op-art de círculos). |
| capa5 (grafik) | 0.612 | Subiu de 0.59 (bônus do mesmo ajuste); hachura é o desafio. |
| capa1 (mosaico) | 0.434 | Difícil — mosaico fino + logo. |
| capa2 (texto) | 0.315 | Fundo domina; texto fino (a métrica está sendo calibrada). |

**Leitura:** o sistema **domina uma classe inteira de capas** (grades, blocos de cor,
triângulos, círculos, texto — capa4/capa6/capa7). O desafio restante são capas com
**padrões complexos** (op-art, mosaico, hachura), que exigem crescer o "vocabulário
visual". Nota de método: a capa7 saltou de 0.67 → 0.87 ao corrigir **um** bug de
renderização — evidência de que o caminho é depurar o compilador, não reescrevê-lo.

## 6. O que já foi conquistado (a arquitetura)

- **Reconstrução fiel** de uma classe inteira de layouts (Score 0.956 na referência).
- **Loop de auto-correção** que, por design, nunca piora o resultado.
- **Mapa de layout** — o sistema entende onde é texto vs. geometria, evitando que o
  texto seja lido como parte do desenho (isso destravou a capa6).
- **Seleção de camadas medida** — uma capacidade rara: quando adicionamos um detector
  novo, o sistema **mede** se ele ajuda e o **rejeita sozinho** se não ajudar. Isso
  elimina o retrabalho de "adicionar algo que quebra e reverter na mão".
- **Métrica honesta** (content_match) — enxerga o conteúdo, não só o fundo.

## 7. Como chegamos ao resultado final (roadmap)

O sistema deixou de ser "conversor de imagem" e está virando um **compilador de
linguagem visual** — entende não só *o que* existe na imagem, mas *como os elementos
se relacionam* (padrões, repetição, simetria).

```
FASE 1  ✅ Nota objetiva (Score) que prioriza conteúdo        — FEITO
FASE 2  ✅ Seleção de camadas medida (anti-retrabalho)         — FEITO
FASE 3  🔨 Reconhecer PADRÕES (periodicidade, hachura, mosaico) — em curso
FASE 4     Mapa de layout completo (segmentar toda a capa)
FASE 5     VLM (modelo de visão) — só como auxílio nas capas ambíguas
```

A estratégia é **uma capa por vez, da mais fácil à mais difícil**, sempre com um
"portão de regressão": nenhuma melhoria pode piorar as capas que já funcionam.

## 8. Limitações honestas

- Capas com **padrões densos e de alta-frequência** (op-art, mosaico fino, hachura)
  são o limite atual — exigem reconhecer padrões, não só objetos isolados.
- A **fonte** é um clone métrico da Helvetica (letterforms batem), não o recorte
  original exato — diferença sutil.
- Há um **teto natural de ~0.95** porque comparamos um vetor renderizado contra uma
  foto (fímbria de sub-pixel). Acima disso é perfeccionismo de métrica, não fidelidade.

## 9. Resumo para decisão

O **núcleo está provado e correto** (capa4). A arquitetura é sólida, determinística e
auto-corretiva. O trabalho restante é **crescer o vocabulário visual** para cobrir mais
estilos de capa — um caminho claro e incremental, não uma reescrita. O sistema já
entrega valor real para a classe de capas que domina hoje.
