---
name: experiment-design
description: Guia para desenhar, rodar e reportar experimentos A/B de comparação de tools/estratégias neste repositório (rag-vs-manual e afins) — cobre a convenção de session_name, o uso de Workflow para gerar e validar respostas via confidence-analysis, e a geração de um report em docs/experiments/ validado com text-lint e canonical-terms. Ativar sempre que eu (o agente) for desenhar um novo experimento comparativo, adaptar um dos scripts em .claude/workflows/rag-vs-manual-*.js para um contexto/pergunta diferente, ou escrever o report de uma rodada já executada.
globs: ["**/*"]
---

# experiment-design

Guia de processo para experimentos comparativos (tool × estratégia × pergunta) neste
repositório, do desenho do `Workflow` script até o report final validado. Não é um gerador
automático — cada experimento novo ainda é um script `.claude/workflows/*.js` escrito/adaptado
sob medida, mas seguindo as diretivas abaixo em vez de reinventar convenções a cada rodada.

## Quando ativar

- Dev pediu para rodar um experimento comparando tools (Claude Code, Copilot CLI, agy) ou
  estratégias (RAG vs. leitura direta, com vs. sem uma flag específica) contra um conjunto de
  perguntas.
- Dev pediu para adaptar `.claude/workflows/rag-vs-manual-single-call.js` (ou um script
  equivalente) para um contexto/projeto diferente do que ele já cobre.
- Uma rodada de `Workflow` já concluiu e o dev pediu o report da rodada.

## Peças do sistema (onde cada coisa vive)

- **Script do experimento**: `.claude/workflows/rag-vs-manual-single-call.js` é o script ativo
  hoje — gera respostas (fase `Generate`) e valida cada uma via
  `/goriok-skills:confidence-analysis` (fase `Validate`), produzindo um `overallScore` (0-10)
  por item. `QUESTIONS`, `CWD`, `CONTEXT_DIR` e `RECALL_COLLECTION` são parametrizáveis via
  `args` (`args.questions`, `args.cwd`, `args.contextDir`, `args.recallCollection`,
  `args.roundPrefix`) — usar isso para rodar o mesmo desenho contra um projeto/pergunta
  diferente, em vez de duplicar o script.
- **Exporter Go**: cada resposta gerada por uma tool tracked (`copilot`, `agy`) vira uma amostra
  em `~/.local/share/ai-tokens-tracker/tsdb/` via `aitokens-exporter track`, com `--task` como
  identificador — ver [[series-session-name-label]] para como isso vira o label `session_name`.
- **VictoriaMetrics**: réplica consultável em `http://127.0.0.1:8428`, alimentada pelo exporter.
- **Dashboard Perses**: `http://localhost:8080/projects/ai-tokens-tracker/dashboards/experiments`
  — filtros `groupA`/`groupB` são campos de texto livre (regex do PromQL), preenchidos com
  `session_name` ou um padrão que casa vários.

## Convenção de nomenclatura do session_name

Formato: `<tool>-<estrategia>-<data>`, com `-` separando cada termo (ex.:
`claude-code-rag-20260910-1000`). `<data>` no formato `YYYYMMDD-HHmm`, passado como
`args.roundPrefix` na chamada do `Workflow`. Objetivo: um prefixo/substring legível é suficiente
para filtrar no dashboard sem precisar de regex complexo — `claude-code-rag` já isola todas as
sessões desse tool+estratégia, independente da rodada.

Não usar termos concatenados sem separador (ex. `claudecoderag20260910`) — dificulta tanto a
leitura humana quanto um filtro parcial por substring.

## Workflow

### 1 — Desenhar o experimento

Definir, antes de escrever/adaptar o script:

- **Pergunta(s)** a comparar — content real do teste, não a estrutura do experimento.
- **Grupos A/B** — normalmente tool×estratégia, mas pode ser qualquer par de configurações
  concretas (ex.: `--disable-builtin-mcps` presente vs. ausente numa mesma tool).
- **Contexto/projeto alvo** — `cwd`, diretório de contexto para RAG/leitura direta, nome da
  collection do `recall-search` se aplicável.
- Se o experimento não se encaixa no desenho tool×estratégia×pergunta já coberto por
  `rag-vs-manual-single-call.js`, decidir se adaptar esse script (parametrizando o eixo que
  varia) ou escrever um novo — preferir adaptar quando o desenho geral (Generate → Validate via
  confidence-analysis) ainda se aplica.

### 2 — Rodar via Workflow

Invocar `Workflow` com o script e os `args` que parametrizam a rodada (perguntas, prefixo de
data, contexto). Cada item gerado carrega um `label` que vira `session_name` — conferir que o
label segue a convenção do `-` antes de disparar a rodada, não depois.

### 3 — Confirmar os dados na store

Depois que o `Workflow` concluir, confirmar que as amostras da rodada realmente aparecem no
VictoriaMetrics com o `session_name` esperado antes de escrever o report — uma falha silenciosa
de propagação de label (já ocorreu uma vez, ver [[series-session-name-label]]) invalida a
comparação sem nenhum erro visível.

```bash
curl -s "http://127.0.0.1:8428/api/v1/label/session_name/values" | grep "<prefixo-da-rodada>"
```

### 4 — Gerar o report

Criar `docs/experiments/<nome-do-experimento>.md`, contendo no mínimo:

- **Contexto**: objetivo do experimento, o que está sendo comparado e por quê.
- **Grupos**: quais `session_name` (ou padrão) compõem o grupo A e o grupo B.
- **Tabela de scores**: uma linha por combinação (pergunta × estratégia × tool), com o
  `overallScore` (0-10) retornado pela fase `Validate`.
- **Link do dashboard**: URL do Perses filtrada para a rodada
  (`http://localhost:8080/projects/ai-tokens-tracker/dashboards/experiments`), com os valores de
  `groupA`/`groupB` usados.
- **Achados**: conclusão em prosa — o que os números sugerem, limitações conhecidas da rodada
  (ex.: item que falhou e não foi reexecutado, bug de instrumentação descoberto durante a
  rodada), próximos passos se houver.

### 5 — Validar o report

Rodar `/goriok-skills:text-lint` sobre o arquivo do report antes de considerá-lo pronto — corrige
parágrafos com múltiplos pontos, tom professoral, hard-wrap artificial e enumerações disfarçadas
de prosa.

Rodar `/goriok-skills:canonical-terms` sobre qualquer mecanismo técnico descrito na seção de
achados (ex.: se o report descreve um padrão de resiliência, concorrência ou arquitetura) — usar
o termo canônico do mercado em vez de uma descrição própria improvisada, consultando/populando
`MAP.md` conforme a skill descreve.

### 6 — Reportar ao dev

Resumo curto: onde o report foi salvo, principais números da tabela de scores, e qualquer achado
que exija decisão do dev (ex.: um bug de instrumentação encontrado durante a rodada, uma
recomendação de próximo experimento).

## Anti-patterns

- ❌ Escrever um script de experimento novo do zero quando `rag-vs-manual-single-call.js` já
  cobre o desenho geral e só precisa de `args` diferentes.
- ❌ Gerar o `session_name` sem `-` separando os termos, ou numa ordem diferente de
  `<tool>-<estrategia>-<data>`, quebrando a consistência entre rodadas.
- ❌ Escrever o report sem antes confirmar no VictoriaMetrics que os `session_name` esperados
  realmente aparecem — ver passo 3.
- ❌ Publicar o report sem rodar `text-lint`/`canonical-terms` sobre ele.
- ❌ Report sem seção de achados/conclusão — uma tabela de números sem interpretação não cumpre
  o propósito do experimento para quem lê depois.

## Veja também

`docs/madrs/MADR-003-timeseries-model-and-go-exporter.md` — o modelo de dados por trás de
`session_name` como label. [[series-session-name-label]] — o bug de propagação de `session_name`
para fontes não-Claude-Code, encontrado ao validar uma rodada real.
