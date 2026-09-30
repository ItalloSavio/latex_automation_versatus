# Como orientar uma nova sessão

> Cole o bloco abaixo como **primeira mensagem** de um chat novo, quando o contexto acabar.
> Ele existe porque sessões anteriores repetiram os mesmos erros: otimizaram por velocidade
> sem pedido, citaram números que vieram de JSON parado em disco, e promoveram entregáveis
> sem olhar. O bloco corta isso na raiz.

---

## O prompt (copie daqui para baixo)

```
Projeto: Swiss Cover Replicator. Você vai continuar um trabalho em andamento.

ANTES DE QUALQUER COISA, leia nesta ordem:
  1. handoff_state.md (na sua memória)  — estado atual, restrições, o que está decidido
  2. CLAUDE.md, seção "RESTRIÇÕES DO PROJETO" e "Protocolo de trabalho"
  3. pos-mvp.md         — a fila, com a evidência medida de cada item e o PLANO EM FASES
  4. pipeline-ideal.md  — o desenho original (a maior parte já construída; histórico)

Depois de ler, me diga em 5 linhas o que você entendeu do estado atual e qual você
acha que é o próximo passo. NÃO comece a trabalhar até eu confirmar.

REGRAS QUE NÃO SE NEGOCIAM NESTE PROJETO:

1. TEMPO NÃO É RESTRIÇÃO. QUALIDADE É.
   1 a 3 capas por rodada. 10-15 min por capa é ótimo, até 30 min é aceitável.
   NUNCA reduza passes, pule o VLM ou corte iteração "para ser rápido".
   Se uma rodada demora, me dê feedback de progresso — não me deixe olhando terminal parado.

2. MEDIR ANTES DE AFIRMAR.
   Todo número que você citar tem que vir de uma rodada real, e diga de qual.
   Renderizar um analysis.json guardado NÃO é rodar o pipeline — essa confusão já produziu
   uma afirmação falsa (capa1 "0.8622" quando o pipeline real dá 0.7304).

3. BACKUP ANTES DE SOBRESCREVER.
   automation/output/ não é versionado. Uma rodada já apagou os JSONs das 9 capas.

4. OLHAR ANTES DE PROMOVER.
   Nenhum entregável entra no MVP/ sem você abrir o PNG e comparar com o original.
   O Score é quase cego a texto — ele já disse "melhorou" nas 4 vezes em que errou feio.

5. ISOLAR UMA VARIÁVEL POR A/B.
   Um A/B confundido já quase descartou um ganho real (half_ellipse: acusou -0.0631,
   isolado deu +0.0007).

6. DETERMINISMO, NÃO ACHISMO.
   Parar porque não há mais o que propor é resposta válida. Parar porque um número cruzou
   um limiar arbitrário, não. Se é teto, meça o teto e registre.

7. DOCUMENTAÇÃO SEMPRE ATUALIZADA — a cada bloco de trabalho, não no fim.
   Fechou um item? Na MESMA rodada atualize: pos-mvp.md (estado do item), o handoff_state.md,
   e o número/veredito no CLAUDE.md. Este arquivo aqui também envelhece — confira-o contra o
   código ao fim de cada fase. Antes de afirmar que algo está "aberto", dê grep no código:
   este arquivo já afirmou que o [PASS] de 0.95 estava aberto duas semanas depois de fechado.

8. REPRODUZIR É PARTE DE TERMINAR.
   Depois de mexer em qualquer coisa que o cache do VLM atravessa, refaça UMA capa pelo cache
   e compare a LISTA DE TEXTOS e o Score com o entregue. Duas vezes o cache devolveu outra capa
   em silêncio (proposta já processada pelo snap; edit endereçado por índice de lista).
   Regra: o cache guarda a PROPOSTA CRUA, endereçada por CONTEÚDO — nunca geometria
   pós-processada, nunca `t3`/`r12`.

Quando terminar qualquer bloco de trabalho, me diga:
  - o que mudou e em quais arquivos
  - o número ANTES e DEPOIS, de rodada real
  - o que você olhou com o olho, não só mediu
  - o que ficou pendente e por quê
```

---

## Por que cada regra está aí — o erro que a originou

| regra | o que aconteceu sem ela |
|---|---|
| 1 · tempo não é restrição | `max_passes=1` foi posto como padrão "por velocidade": **calibrador inerte nas 9 capas**, 3 capas travadas fora do VLM |
| 2 · medir antes de afirmar | capa1 "automática dá 0.8622" — era JSON parado; o pipeline dá **0.7304** |
| 3 · backup | uma rodada apagou os `analysis.json` das 9; recuperados por sorte |
| 4 · olhar antes de promover | as 9 foram promovidas por número; a folha revelou 2 defeitos, 1 introduzido na mesma sessão |
| 5 · isolar variável | A/B do `half_ellipse` acusou −0.0631 com a causa em outro lugar |
| 6 · determinismo | o `[PASS]` de 0.95 **bloqueava o VLM** em 3 das 9 capas — inclusive numa com texto borrado (corrigido em 14/09: o estágio 13 não consulta mais o limiar) |
| 7 · docs sempre atualizados | o `handoff_state.md` ficou **um mês vencido**; e em 30/09 este próprio arquivo afirmava que o `[PASS]` de 0.95 estava aberto (fechado desde 14/09) e tinha a lista de próximos passos **inteira** já resolvida |
| 8 · reproduzir é terminar | o cache do VLM **nunca reproduziu as capas que gerou** — duas causas, meio dia perdido atribuindo a regressão à mudança errada |

## Se a sessão for retomar o trabalho técnico

### Onde o projeto está (30/09)

**MVP: 9 capas · média 0.9034 · 4 em ≥ 0.95 · portão 8/9 OK · auditoria 9/9.** O único
`ATENCAO` é o título da capa1 (mesma causa de polaridade que já foi corrigida na capa8; a capa1
tem cirurgia manual e pede tratamento próprio).

**O motor de replicação atingiu platô NESTE corpus — medido:** 8 das 9 capas estão no teto da
imagem-fonte (56–89 dpi; 50–92% das linhas abaixo do piso de 16px), os últimos ganhos vieram
todos de BUGS e não de capacidade nova, e o que resta do motor está bloqueado ou rende pouco.
⚠️ **As capas NÃO podem ser reexportadas** ("foram entregues assim") — o teto é permanente para
estas 9. Não proponha de novo.

**O produto NÃO atingiu platô.** O trabalho agora é robustez + produto, em três fases acordadas
com o usuário em 30/09:

| fase | o quê | estado |
|---|---|---|
| **1** | fechar a cadeia do produto: capa DENTRO do livro · `--dpi` automático · quantizador em blocos · progresso visível no `cover_pipeline` | ✅ **feita 30/09** — `--livro`, `render_dpi()`, `_nearest_palette`, `_progresso.md` |
| **2** | limpeza e documentação oficial (9 markdowns na raiz → conjunto claro) | ⏸️ **aguarda orientação do usuário** |
| **3** | sistema amigável: **CLI guiada** — o usuário conhece CLI mas não sabe que comando rodar | ⏸️ **aguarda orientação do usuário** |

⚠️ **A Fase 1 terminou e foi REPORTADA em 30/09. NÃO comece a 2 nem a 3 sem a orientação do
usuário.** Achado dela que também espera decisão: o **tempo por render** de capa em alta
(~4–5 min) tem duas causas medidas com conserto pequeno e resultado idêntico — `np.unique(axis=0)`
no comparador (107× mais lento que `bincount`) e o `luaotfload` reconstruindo o banco de fontes
a cada compilação (75 s → 21 s). Ver `pos-mvp.md`, "Achados da Fase 1".

### Já feito — não refaça

| item | quando |
|---|---|
| juiz enxerga AUSÊNCIA (quadro congelado) · palavras coladas em display · laço roteado · `max_passes`=3 · passe de refinamento · cache do VLM fiel | 16–18/09 |
| teto de resolução medido + estágio de aviso (`_report_resolution`) · regra de parágrafo no OCR | 23–25/09 |
| `text.add` não desenha sobre arte traçada · réguas mascaradas no OCR (parcial) · aterramento recusa no-op · **polaridade da tinta** (capa8 `ATENCAO`→`OK`) · 249 linhas mortas removidas | 28/09 |
| `[PASS]` de 0.95 como parada — **não existe mais** (removido em 14/09; o laço só para quando nada é aceito) | conferido 28/09 |
| **Fase 1**: capa no livro (`--livro`) · `--dpi` automático · quantizador em blocos · `_progresso.md` · `apply_art` move o baseline junto · `audit`/`accept` sem argumentos não quebram mais | 30/09 |

### Bloqueado, com motivo

- **Gradiente (§B1)** — sem caso de teste; a imagem do teste frio de 14/09 sumiu do repositório.
- **capa1** — a correção de polaridade muda 9 elementos dela, mas o entregável é cirurgia manual.
- **4 letras fantasma no pôster** — a régua da grade encosta no glifo; a sonda não separa.
