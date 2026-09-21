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
  3. pipeline-ideal.md  — o desenho acordado e ainda não construído
  4. pos-mvp.md         — a fila, com a evidência medida de cada item

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

7. ATUALIZE O handoff_state.md ENQUANTO TRABALHA, não no fim.
   Se o contexto reiniciar no meio, o próximo tem que saber onde a mão parou.

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
| 6 · determinismo | o `[PASS]` de 0.95 **bloqueia o VLM** em 3 das 9 capas — inclusive numa com texto borrado |
| 7 · atualizar o handoff | o `handoff_state.md` ficou **um mês vencido**, descrevendo 20 capas e um plano concluído |

## Se a sessão for retomar o trabalho técnico

O próximo passo acordado com o usuário, em ordem:

1. **Remover o `[PASS]` de 0.95** como condição de parada (ver `pipeline-ideal.md` §4.2 e o
   achado de 14/09: capa4, capa6 e capa12 estão travadas fora do VLM).
2. **Passe de refinamento pós-build** (`pipeline-ideal.md` §4.7) — separado do pipeline,
   de propósito. É o desenho do usuário.
3. **Roteamento de métrica dentro do laço** (§4.1).
4. **`max_passes` = 3** — só depois de (3).

⚠️ Antes de mexer no juiz, **reescrever o `judge_bench.py`** (`pos-mvp.md` §A2). Ele não existe,
e mexer no Score sem banco de provas já quebrou quatro capas uma vez.
