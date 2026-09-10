# Handbook: conceitos e stack de experimentos

Referência conceitual para desenhar, interpretar e depurar experimentos comparativos
(`docs/experiments/`). Complementa o procedimento passo a passo em
[rodar-experimentos.md](../runbooks/rodar-experimentos.md) — este documento explica o porquê,
não o como executar.

## A stack por trás de um experimento

Um experimento neste repositório mede consumo real de token de CLIs de IA (Claude Code, Copilot
CLI, agy) respondendo a perguntas técnicas, sob estratégias de leitura diferentes. A stack tem
três camadas:

- **Exporter Go** (`exporter/`) — lê transcripts locais (Claude Code) ou grava diretamente via
  `track`/`delegate` (Copilot, agy) num TSDB append-only local. Serve `/metrics` no formato
  Prometheus.
- **VictoriaMetrics** — réplica consultável via PromQL, alimentada pelo exporter via
  `export-vm` (passo manual, desacoplado da ingestão).
- **Perses** — dashboards versionados como código (`perses/provisioning/`), consultando o
  VictoriaMetrics.

```text
+----------------------------------------------------------------------------+
| Perses                                                                     |  -- dashboards versionados como codigo, consulta VictoriaMetrics via PromQL
+----------------------------------------------------------------------------+
| VictoriaMetrics                                                            |  -- replica consultavel, alimentada via export-vm (passo manual, desacoplado)
+----------------------------------------------------------------------------+
| Exporter Go                                                                |  -- le transcripts locais ou grava via track/delegate; serve /metrics
+----------------------------------------------------------------------------+
```

O modelo de dados completo está em
[MADR-003](../madrs/MADR-003-timeseries-model-and-go-exporter.md).

## Fluxo end-to-end de um item de experimento

Cada item de um experimento (uma combinação pergunta × estratégia × tool) segue duas fases,
orquestradas pela tool `Workflow`:

1. **Generate** — um agente roda o comando real da tool (`claude -p`, ou
   `aitokens-exporter track` para Copilot/agy) e captura o `rawOutput`.
2. **Validate** — um agente separado avalia o `rawOutput` usando a skill
   `/goriok-skills:confidence-analysis`, retornando `overallScore` e uma lista de `claims`.

<!-- mermaid source:
sequenceDiagram
    participant Workflow
    participant AgenteGenerate
    participant CLI
    participant AgenteValidate
    Workflow->>AgenteGenerate: agent(generatePrompt)
    AgenteGenerate->>CLI: Bash(claude -p / aitokens-exporter track)
    CLI-->>AgenteGenerate: rawOutput
    AgenteGenerate-->>Workflow: rawOutput
    Workflow->>AgenteValidate: agent(validatePrompt)
    AgenteValidate-->>Workflow: overallScore + claims
-->
```text
+----------+     +----------------+     +-----+     +----------------+
| Workflow |     | AgenteGenerate |     | CLI |     | AgenteValidate |
+-----+----+     +--------+-------+     +--+--+     +--------+-------+
      |                   |                |                 |
      | agent(generatePrompt)              |                 |
      +------------------>|                |                 |
      |                   |                |                 |
      |                   | Bash(claude -p / aitokens-exporter track)
      |                   +--------------->|                 |
      |                   |                |                 |
      |                   | rawOutput      |                 |
      |                   |<...............+                 |
      |                   |                |                 |
      | rawOutput         |                |                 |
      |<..................+                |                 |
      |                   |                |                 |
      | agent(validatePrompt)              |                 |
      +----------------------------------------------------->|
      |                   |                |                 |
      | overallScore + claims              |                 |
      |<.....................................................+
      |                   |                |                 |
```

Claude Code e Copilot gravam a amostra de forma diferente: o Copilot grava de forma síncrona
dentro do próprio comando `track`, antes de retornar; o Claude Code só escreve seu transcript
local, que um serviço separado (`ai-tokens-exporter.service`) lê depois, de forma assíncrona. Um
diagrama de sequência completo está em
[rag-vs-manual-single-call-copilot-vs-claude.md](../experiments/rag-vs-manual-single-call-copilot-vs-claude.md).

## `session_name`: o label que permite comparação A/B

`session_name` é o único label de alta cardinalidade potencial no modelo de métricas — todos os
outros (`session_id`, `agent_id`, `request_id`) ficam de fora por cardinalidade inviável (medida
em centenas de milhares de valores distintos). `session_name` é a exceção deliberada porque seu
crescimento não é proporcional ao volume de requests, só a quantas vezes alguém nomeou uma
sessão.

A mitigação de crescimento é retenção por tempo no VictoriaMetrics (60 dias), não exclusão do
label.

Isso faz de `session_name` o mecanismo de comparação A/B do dashboard de experimentos: o
`roundPrefix` e o rótulo de cada item (`<tool>-<estrategia>-<data>`) viram o `session_name` da
sessão, e o dashboard filtra por esse valor.

**Limitação conhecida:** `session_name` só é gravado corretamente quando a fonte propaga o label
até o exporter. Um bug já corrigido (commit `256e415`) fazia `TaskCallSamples`/`CopilotSamples`
descartarem esse label — rodadas anteriores a esse fix têm sessões Copilot sem `session_name`,
não filtráveis no dashboard mesmo com dado no storage local.

## Os 4 tipos de token

O exporter mede 4 tipos de token, na terminologia da Claude API, todos sob a métrica
`aitokens_tokens_total{token_type=...}`:

- **`input`** — tokens processados normalmente, sem vir de um prefixo já em cache.
- **`output`** — tokens gerados pelo modelo na resposta.
- **`cache_read`** — tokens servidos a partir de um prefixo de prompt já em cache, em vez de
  reprocessados do zero.
- **`cache_creation`** — tokens escritos para o cache numa chamada, disponíveis para leitura em
  chamadas futuras dentro do TTL da entrada.

`cache_creation` acontece uma vez, quando um prefixo de prompt (código-fonte lido, doc de
contexto) entra no cache pela primeira vez. Toda chamada seguinte que reaproveita esse mesmo
prefixo conta como `cache_read`. Em experimentos com múltiplas chamadas na mesma sessão/repo,
`cache_read` tende a dominar o volume total — reflexo de releitura de contexto já visitado, não
de conteúdo novo.

**`cache_creation_measured`** é um gauge separado (`aitokens_cache_creation_measured{source}`,
0/1) que distingue "não medido" de "confirmado zero". Existe porque a CLI do `agy` não expõe o
campo de cache-write — sem esse gauge, `agy` leria como artificialmente mais barato em qualquer
comparação de cache entre fontes.

## Score e claims (`confidence-analysis`)

A fase `Validate` usa a skill `/goriok-skills:confidence-analysis` para decompor cada `rawOutput`
em **claims** — cada afirmação factual individual dentro do texto, não a resposta inteira de uma
vez. Cada claim recebe:

- Um nível de confiança de 0 a 10 (0-3 evidência fraca, 4-6 inferência moderadamente sustentada,
  7-10 evidência forte).
- Um label textual fixo (`"This is a well-supported fact"`, `"This is an inference"`,
  `"This is a guess"`, entre outros).
- Um tier de fonte, numa hierarquia de 6 níveis onde 1 é evidência direta observável (código,
  config, output real) e 6 é conhecimento geral sem verificação específica.

O `overallScore` do item é a síntese que o agente validador faz a partir dos claims — a média, ou
o score da claim mais frágil que sustenta a resposta, sem uma regra fixa prescrita entre as duas.
Uma claim que dependeria de acesso externo não disponível ao validador é limitada a no máximo
6/10, mesmo que a citação esteja correta.

**Limitação conhecida:** o score só é confiável quando a fase `Validate` tem acesso ao mesmo
repositório que o item avalia. Numa rodada documentada em
[copilot-github-mcp-authn-authz.md](../experiments/copilot-github-mcp-authn-authz.md), o
validador rodou sem esse acesso e tratou os dois braços comparados de forma assimétrica —
produzindo uma diferença de score que refletia a limitação do validador, não a qualidade real das
respostas.

## Erros de instrumentação já encontrados

Registrados aqui porque tendem a se repetir em rodadas novas se não forem checados:

- **`looksLikeRealAnswer` não filtra mensagens de bloqueio do harness.** Um bloqueio de "auto
  mode safety" do Claude Code, ou um safeguard de segurança da API (`[cyber]`), pode passar pelo
  filtro de tamanho mínimo do script e seguir para validação como se fosse resposta técnica real
  — produzindo um score baixo mas não-nulo em vez de um item corretamente marcado como sem dado.
- **`session_name` ausente silenciosamente** para fontes que não propagam o label (ver seção
  acima) — sempre confirmar no VictoriaMetrics antes de escrever o report (passo 4 do runbook).
- **Export para VictoriaMetrics é manual e desacoplado.** Uma rodada pode ter dado completo no
  storage local do exporter e ainda assim não aparecer no dashboard, porque `export-vm` não
  rodou.

## Veja também

- [rodar-experimentos.md](../runbooks/rodar-experimentos.md) — procedimento passo a passo.
- [MADR-003](../madrs/MADR-003-timeseries-model-and-go-exporter.md) — modelo de dados completo.
- `.claude/skills/experiment-design/SKILL.md` — diretivas de desenho e nomenclatura.
