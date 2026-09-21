# Swiss Cover Replicator — Revisão do Projeto

> Documento executivo. Estado atual, como funciona, como medimos, o que está pronto e o que falta.
> **Atualizado em 2026-09-16.** A versão anterior era de julho e descrevia 7 capas e um sistema
> sem integração de conteúdo — as duas coisas mudaram.

---

## 1. O que é, em uma frase

Um sistema que **recria uma capa de design suíço como um PDF vetorial editável**, a partir de
uma imagem. Você manda um PNG → sai um PDF (LaTeX/TikZ) visualmente igual — e o sistema
**mede o próprio resultado e se corrige** até não ter mais o que melhorar.

Não é "gerar uma capa parecida". É **reconstruir aquela capa específica**, e como **estrutura**
(um círculo é um círculo, um texto é um texto), não como cópia de pixels.

## 2. Por que essa abordagem importa

- **Determinístico** — mesma entrada, mesma saída. O código TikZ não é escrito por IA
  generativa; cada coordenada vem de uma medição nos pixels.
- **Editável** — a saída é vetorial (texto, formas e cores como objetos), não uma imagem.
  Ajusta-se qualquer elemento depois e imprime em qualquer tamanho.
- **Auto-corretivo** — o sistema renderiza, compara com a original, corrige e repete; uma
  correção só é aceita se melhorar, então **o resultado nunca piora**.
- **Auditável** — existe uma ferramenta que verifica se o arquivo entregue corresponde
  exatamente à análise que o gerou. Hoje: **9 de 9**.

## 3. Como funciona

```
   IMAGEM
     │
     ├─ [OCR]          lê o texto, onde está, o tamanho, o peso e a cor da tinta
     │
     ├─ [Visão]        quantiza as cores e separa a capa em componentes; para cada um,
     │                 testa qual primitivo (círculo, retângulo, triângulo, meio-disco,
     │                 polígono) melhor EXPLICA aqueles pixels e mede o encaixe
     │
     ├─ [Portões]      três decisões tomadas por MEDIÇÃO, não por confiança:
     │                 qual leitor usar · qual camada manter · qual texto é real
     │
     ├─ [Gerador]      monta o PDF vetorial
     │
     ├─ [LOOP]         compara com a original → corrige → repete
     │                 (calibra tipografia, recolore regiões)
     │
     ├─ [VLM]          um modelo de visão compara as duas imagens e propõe correções
     │                 tipadas; cada uma passa por um portão que mede e pode rejeitar
     │
     └─ [VEREDITO]     "esta capa saiu entregável?" — verificação de defeito estrutural
```

**O diferencial é o loop com portão.** O sistema não tenta acertar de primeira: ele renderiza,
mede a diferença, corrige, e mede de novo. E nada entra sem passar por medição — inclusive as
propostas do modelo de visão, que são rejeitadas uma a uma quando não melhoram.

## 4. Como medimos

Uma nota, o **Score** (0 a 1):

| Componente | O que mede | Peso |
|---|---|---|
| **content_match** | qualidade só no conteúdo, ignorando o fundo | 50% |
| **SSIM** | similaridade estrutural geral | 30% |
| **content_iou** | se o conteúdo está no lugar certo | 20% |

**Por que não só SSIM:** ele engana. Uma capa 75% preta ganha nota alta só acertando o fundo,
mesmo faltando todo o conteúdo — um caso real teve SSIM 0.94 reproduzindo 3% do conteúdo.

### ⚠️ O aprendizado mais importante do projeto

**O Score é quase cego a texto, e descobrimos isso da forma mais cara possível.** Quatro casos
medidos onde o número disse "melhorou" e o resultado piorou:

| o que aconteceu | o que o Score fez |
|---|---|
| uma capa perdeu metade do título | **subiu** 0.055 |
| outra teve o título apagado, virou buraco | subiu 0.003 |
| uma capa lê um anel gráfico como o dígito "6" gigante | **remover o erro custa 0.13** |

Por isso o sistema ganhou **um segundo juiz**, independente do Score: um verificador de
**defeito estrutural** — texto vazando da página, blocos sobrepostos, tipo grande demais para
ser tipo, letra desenhada como mancha. Ele não mede semelhança; ele responde *"isto está
quebrado?"*.

### ✅ Resolvido em 16/09: ele passou a enxergar o que FALTA

Até então esse verificador tinha um buraco: olhando só o resultado final, **não havia como saber
o que sumiu**. A capa que perdeu metade do título era aprovada.

A causa não era falta de uma regra — era falta de uma **referência**. A régua que mediríamos o
texto era construída a partir do próprio resultado sendo julgado, então o elemento omitido
simplesmente não era cobrado: **apagar saía de graça.** A correção foi congelar, uma vez, o que
o sistema lê na imagem original, e passar a medir todo candidato contra essa régua fixa.

Resultado medido: a capa que saiu pela metade passa de *aprovada* para **"revisar"**, apontando o
problema pelo nome — *"o original lê 'the' aqui (1% da página) e o entregável não põe quase
nada"*. E a versão correta continua aprovada, sem alarme falso.

**O placar caiu de 8/9 para 7/9 — e nenhuma capa piorou.** O que mudou foi o juiz: a capa1 passou
a acusar um defeito que sempre esteve lá (o título sai maior e deslocado). Um número de aprovação
só é comparável dentro da mesma versão do verificador.

**Consequência prática:** a validação final continua sendo **o olho humano**, com uma ferramenta
que monta original × gerada lado a lado. O número prioriza; o olho decide. Mas o sistema já
recusa sozinho uma classe de defeito que antes passava batida.

## 5. Estado atual — as 9 capas do MVP

**Média 0.90 · auditoria 9/9 · veredito estrutural 7/9 · oito das nove saem de um comando.**

| Capa | Score | Situação |
|---|---|---|
| capa4 (david bowie) | **0.967** | Referência. Praticamente indistinguível da original. |
| capa12 (Friends) | **0.956** | Círculos sobrepostos com transparência. |
| capa6 (rancid) | **0.952** | O modelo de visão corrigiu 6 linhas de texto que o OCR errava. |
| capa8 (velvet underground) | **0.938** | Entrou "fria" no conjunto e já marcou 0.93. |
| capa13 (YOU) | **0.930** | Era 0.49 antes da reescrita do leitor. |
| capa16 (vision) | **0.919** | Malha de losangos; era 0.41. |
| capa19 (the shining) | **0.904** | Ganhou 0.067 num único passe de visão. |
| capa1 (mosaico Versatus) | **0.818** | **A exceção** — depende de ajuste manual (ver §8). |
| capa2 (Versatus texto) | **0.723** | 96% fundo com tipografia fina; o número mente para baixo. |

### A prova do produto

Em 14/09 testamos a promessa de verdade: **uma imagem inédita, sob nome novo, sem nada em
cache, por um único comando.** Resultado **0.932**, PDF gerado, e o verificador apontando
sozinho o único defeito real. É o produto exercido como um usuário o exerceria.

## 6. O que já está conquistado

- **Um leitor genérico** no lugar de um detector por tipo de forma. Produz 8 das 9 capas.
  Foi a mudança que levou capa13 de 0.49 para 0.93 e capa16 de 0.41 para 0.92.
- **Portões medidos** — quando adicionamos um detector novo, o sistema mede se ele ajuda e o
  **rejeita sozinho** se não ajudar. Elimina o retrabalho de "adiciona, quebra, reverte à mão".
- **Modelo de visão como proponente, nunca protagonista** — ele sugere correções tipadas
  (dado, nunca código) e um portão aceita ou rejeita **uma a uma**. Numa capa ele propôs 12
  correções e o portão rejeitou todas as 12, sem prejuízo.
- **Comando único** — `cover_pipeline.py minha_capa.png`. Aceita qualquer PNG.
- **Segunda camada, opcional** — a mesma arte recebendo o conteúdo do livro (títulos do
  metadata e a marca real), com direção de arte fixável à mão quando o designer quiser.
- **Auditoria automática** — o arquivo entregue corresponde à análise que o gerou.

## 7. Como isto entra no livro

A capa gerada é um comando LaTeX que o template já sabe consumir (`\VSBookCoverDynamic`).
A fiação existe e está testada.

⚠️ **Ressalva honesta:** esse elo é o **único da cadeia que ainda não foi demonstrado
ponta a ponta** — ninguém compilou o livro final com uma das nove capas dentro. O arquivo que
ocupa esse lugar hoje é de outro fluxo. 

## 8. Limitações honestas

**Tetos estruturais — não se resolvem com mais engenharia:**

- **A fonte** é um clone métrico da Helvetica (as larguras batem, o desenho das letras não).
  A original é licenciada e paga.
- **O OCR erra caracteres** nessas resoluções, em qualquer escala. Testamos ampliar a imagem
  3× e `"buffalo, new york"` continua saindo `"bullalo; ncw york"`. **Só o modelo de visão
  corrige** — e corrige bem, mas custa chamada de API.

**Limites do vocabulário — têm solução, ainda não construída:**

- **Gradiente** não existe como primitivo. Um fundo em degradê vira manchas de cor chapada.
  Apareceu no teste da imagem inédita e atinge qualquer pôster com degradê.
- **Composição** — nenhum primitivo diz "esta peça está por cima daquela". É o que impede a
  ponta de uma forma recortada de fechar corretamente numa das capas.

**A exceção conhecida — capa1:** o OCR lê o anel gráfico dela como um dígito "6" de 411pt, e
**remover esse erro custa 0.13 de Score** — então o portão medido o mantém: certo pelo número,
errado pelo olho. Essa capa continua dependendo de um ajuste manual.

⚠️ **O trabalho de 16/09 não destravou a capa1, e é importante não confundir as duas coisas.**
O verificador agora *acusa* o problema (ele reprova a versão automática e aponta o título fora de
lugar na entregue), mas quem escolhe manter ou remover o "6" durante a construção é a **nota**, e
a nota não foi alterada — de propósito, porque alterá-la com três casos de teste é exatamente o
movimento que quebrou quatro capas em agosto. Ganhamos o alarme; falta a decisão automática.

## 9. Próximos passos

Em ordem, com a justificativa de cada um:

**1 · Um juiz que enxergue conteúdo ausente** — ✅ **FEITO em 16/09** (§4). O verificador passou
a medir contra uma referência congelada e agora recusa sozinho a capa que perde conteúdo.
O banco de provas do juiz foi reescrito antes de tocar em qualquer coisa, como exigido.

⚠️ **Duas ressalvas honestas.** (a) A nota (o Score) **não** foi alterada — o juiz novo entrou
como *portão*, não como função objetivo. Repesar a nota foi testado e **não** resolve o caso da
capa1, porque ali o mecanismo do erro é outro; e três casos de teste são poucos para calibrar
pesos, exatamente o erro que quebrou quatro capas em agosto. (b) Um caso do banco continua sem
solução: quando o texto original é *ilegível para o OCR*, não há referência para cobrar, e só o
modelo de visão resolve.

**2 · Passe de refinamento pós-construção**
Um processo separado que abre a imagem original ao lado da capa gerada, identifica **onde o
sistema decidiu errado** (ex.: recusou um texto que claramente existe), e corrige. Fica
deliberadamente **fora** do pipeline principal: o detector interno é cego a tipografia fina
por construção, e um modelo de visão comparando as duas imagens não é.

**3 · Gradiente como primitivo**
Bloqueia qualquer pôster com fundo em degradê. Desenho conhecido, ainda não construído.

**4 · Provar a capa dentro do livro** 
Fechar o único elo não demonstrado da cadeia.

**5 · Identificação de fonte**
O sistema reportaria *"esta capa pede Akzidenz-Grotesk"* — informação acionável para decidir
sobre licenciamento, mesmo sem ter o arquivo.

### Restrições que orientam as decisões

- **Tempo não é restrição; qualidade é.** O uso real é de 1 a 3 capas por rodada, e 10 a 30
  minutos por capa é aceitável. Nenhuma escolha deve trocar fidelidade por velocidade.
- **Poucas imagens, o mais próximas possível do original.** É fidelidade, não volume.

## 10. Resumo para decisão

O núcleo está **provado, medido e auditável**. Oito das nove capas saem de um comando a partir
do PNG, com média 0.90 e verificação automática de que o entregável corresponde à análise.
A arquitetura é a certa: medir em vez de confiar, reverter em vez de esperar.

O trabalho restante **não é reescrita** — é dar ao sistema um juiz que concorde com o olho
humano. Em 16/09 demos o passo mais importante disso: ele já **recusa sozinho** uma capa que
perdeu conteúdo, apontando o que falta pelo nome. O que ainda não faz é **decidir sozinho** —
o alarme existe, mas a nota que guia a construção continua quase cega a tipografia, e mexer nela
exige mais casos de teste do que temos. É essa a distância que resta entre "automatizado" e
"automático", e ela está mapeada, medida e com caminho definido.
