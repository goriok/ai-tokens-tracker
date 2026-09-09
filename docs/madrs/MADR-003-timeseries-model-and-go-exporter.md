# MADR-003: modelo timeseries com exporter Go, TSDB próprio e VictoriaMetrics local

**Status:** approved

## Contexto

O SQLite atual (`~/.local/share/ai-tokens-tracker/usage.db`) guarda uso de token de forma
relacional e não tem camada de agregação: `core/usage.py` carrega **todos** os eventos em
memória (`collect_usage_events`), filtra por `since`/`until` em Python com comparação de string,
e o dashboard soma tudo em JavaScript no browser (`token_dashboard_server.py`). Os índices em
`timestamp` existem e nunca são usados por um `WHERE` no lado do store. Com ~2.000–3.000
eventos/dia em dias ativos (~700k/ano projetado), esse caminho tem prazo de validade curto —
principalmente para perguntas do tipo "tokens por dia/modelo nas últimas 4 semanas", que são
exatamente o caso de uso que uma linguagem de query temporal (PromQL) resolve bem e SQL ad-hoc
resolve mal sem reescrever a camada de agregação.

Decisão de produto (não deste MADR, já tomada com o usuário): introduzir um modelo timeseries
de verdade — um serviço Go que expõe `/metrics` no formato Prometheus, consultável via PromQL —
coexistindo com o SQLite/CLI/dashboard/widget atuais sem quebrá-los, com a intenção de que o
modelo timeseries se torne a fonte única no futuro.

## Decisão

### A tensão: TSDB próprio + `/metrics` — por que não é duplicação de verdade

Um serviço com storage próprio de séries temporais **e** um endpoint `/metrics` scrapeado por um
segundo sistema (VictoriaMetrics) pareceria criar duas cópias divergentes da mesma série. Não é
o caso, porque as duas peças respondem a horizontes temporais diferentes:

- **Storage próprio (`exporter/internal/tsdbstore`) = única fonte de verdade histórica.** Recebe
  cada amostra com o **timestamp real do evento** — incluindo eventos de semanas atrás, no
  backfill inicial. Isso é o que `/metrics` estruturalmente não pode fazer: o formato de
  exposição do Prometheus só representa "o valor de cada série agora"; quem carimba o tempo é
  sempre o scraper, no momento do scrape.
- **`/metrics` = espelho do estado corrente**, servido a partir do último valor conhecido de
  cada série no storage próprio. Um scraper (VictoriaMetrics) que faz pull periódico constrói
  sua própria série a partir de observações repetidas do presente — exatamente como
  Prometheus/VM sempre funcionaram; nenhum exporter convencional tenta reinjetar histórico via
  `/metrics`.

Consequência prática: o **backfill do histórico completo (91.744 amostras, ~700 séries) nunca
passa por `/metrics`** — é escrito direto no storage próprio via `ingest.Backfill`, ordenado
globalmente por timestamp antes do append (ver seção seguinte). O VictoriaMetrics, quando
instalado, só enxerga dados a partir do momento em que começa a scrapear; ele não é uma segunda
fonte de verdade, é um espelho consultável em quase-tempo-real.

**Corolário que ficou faltando na primeira entrega deste MADR**: se o VictoriaMetrics só vê o
scrape, o vmui nunca mostraria a evolução histórica real (semanas de dados já backfilled) — só
uma linha reta a partir do momento da instalação. Resolvido com `exporter/internal/vmimport`: um
subcomando (`aitokens-exporter export-vm`) que lê o storage próprio inteiro
(`tsdbstore.Store.AllSamples`) e faz POST para o endpoint `/api/v1/import` do VictoriaMetrics —
que, ao contrário do scrape, aceita timestamp explícito por amostra. `install-victoriametrics.sh`
roda isso automaticamente após a instalação; reexecutável a qualquer momento (idempotente:
reimportar a mesma amostra é no-op no VM). Esse comando não faz parte do storage próprio nem do
loop de ingestão — é estritamente um adaptador de saída para essa peça de visualização opcional.

### TSDB próprio, não `github.com/prometheus/prometheus/tsdb` — decisão revertida com medição

O plano original usava a biblioteca oficial do TSDB do Prometheus embutida no processo Go. Foi
implementada, e então revertida após medição:

- `go.sum` saltou de 50 para **496 linhas**.
- Build limpo (`go clean -cache && go build ./...`) levou **~44s**.
- Causa raiz: `tsdb/db.go` e `tsdb/head.go` (arquivos centrais do próprio pacote `tsdb`, não algo
  periférico) importam `prometheus/prometheus/config` → `discovery`, que arrasta service
  discovery de todo provedor de nuvem: `k8s.io/client-go`, e os SDKs inteiros de AWS, Azure e
  GCP. Confirmado com `go mod why -m k8s.io/client-go`. Intrínseco ao pacote — não removível sem
  fork.

Substituído por `exporter/internal/tsdbstore`: um log append-only em JSON-lines (uma amostra por
linha) mais um índice em memória do último valor por série, reconstruído por replay na abertura.
Aceita timestamp arbitrário por amostra — a única propriedade que este projeto de fato precisa de
um "TSDB". `go.sum` permanece em 50 linhas.

**Trade-off aceito conscientemente:** sem PromQL nativo local, sem compaction, sem WAL/replicação
prontos. Para o volume medido (dezenas de milhares de amostras/ano, poucas centenas de séries
ativas — ver cardinalidade abaixo), um arquivo texto ordenável por replay é suficiente; quem quer
consulta expressiva usa o VictoriaMetrics, que já resolve isso bem e já era a peça de
visualização decidida.

### Ordenação: checkpoint por `id`, backfill ordenado globalmente, incremental por janela pequena

Medido no banco real (`claude_code_usage_events`, 22.417+ linhas):

| Regime | Defasagem out-of-order máxima | Amostra |
|---|---|---|
| Histórico completo (desde `id=1`) | **23,16 dias** | transcripts antigos descobertos tarde |
| Regime permanente (`id > 20000`) | **~9 minutos** | múltiplos transcripts lidos no mesmo ciclo de 5min |

O `id` autoincrement é a ordem de chegada real (com gaps, por causa de `INSERT OR IGNORE` em
conflitos de `request_id` — inofensivo para um cursor `WHERE id > N`) e é monotônico; o
`timestamp` **não é** — 627 casos medidos onde o timestamp cai conforme o `id` sobe. Um cursor
por timestamp perderia permanentemente qualquer linha que chegasse depois com data anterior ao
`since` já processado. Por isso o checkpoint de leitura (`checkpoint.State`, persistido em
`ingest_state.json` no diretório do próprio exporter, nunca no `usage.db` do Python) é sempre por
`id`.

A defasagem de 23 dias é artefato exclusivo do backfill inicial — não do regime de operação.
Dois modos de ingestão, sem meio-termo:

- **`ingest.Backfill`** (one-shot): lê tudo, ordena **globalmente por timestamp** em memória, e
  só então faz append. Não depende de nenhuma janela de tolerância a desordem — 91k amostras
  cabem em memória sem custo relevante. Recusa reexecutar se já houver
  `BackfillCompletedAt`, a menos que `--force`.
- **`ingest.Incremental`** (loop contínuo, ciclo default de 1 minuto): lê só o delta desde o
  checkpoint, ordena **o lote** por timestamp (corrige as inversões pequenas de ler múltiplos
  arquivos no mesmo ciclo), e conta com a defasagem residual entre lotes ficar dentro de minutos
  — dado que o storage próprio não rejeita amostras fora de ordem (não tem compaction para
  proteger), essa garantia é apenas de correção da série no storage, não uma restrição rígida
  como seria num TSDB com blocos comprimidos.

### Modelo de métricas

Um counter, `aitokens_tokens_total`, com label `token_type` ∈
`{input, output, cache_read, cache_creation}` — não quatro métricas separadas. A pergunta mais
comum ("total gasto") vira `sum(...)` sobre o label na query, em vez de somar quatro nomes de
métrica à mão; isso também resolve, na query e não no código, a divergência hoje existente entre
o backend (`core/model.py`, soma as 4 dimensões) e o frontend do dashboard (soma 3 por padrão,
exclui `cache_creation`).

Labels: `source`, `model`, `project`, `git_branch`, `agent_kind`, `token_type`. Cardinalidade
medida no banco real: `source × model × project` → 60 combinações; `model × project ×
git_branch × agent_kind` → 104. Multiplicado por `token_type` (4), fica na faixa de 250–450
séries ativas — trivial.

`agent_kind` (`main`/`sub`, derivado de `agent_id != ""`) substitui o `agent_id` cru (524 valores
medidos, cardinalidade inviável como label) — mantém a distinção analiticamente útil (22% dos
eventos do Claude Code são de subagentes) sem explodir a cardinalidade. Ficam **fora** dos
labels, por cardinalidade: `session_id` (267), `agent_id` cru (524), `request_id` (22.387).

`aitokens_cache_creation_measured{source}` (gauge, 0/1) preserva a distinção que
`core/model.py`'s `cache_creation_measured` já modela: para `source=agy`, `cache_creation_tokens`
é sempre 0 porque a CLI não expõe esse campo — "não medido", não "confirmado zero". Sem esse
gauge, agy leria como artificialmente mais barato em qualquer comparação de cache-write entre
fontes.

`aitokens_quota_remaining_ratio{model_group}` é um gauge separado — fração de quota semanal
restante do agy, não uma contagem de token; nunca somado com `aitokens_tokens_total`. `model_group`
é slugificado (`"Gemini Models"` → `gemini_models`) para ficar ergonômico em PromQL.

O Copilot carimba a sessão inteira no `startTime` da sessão (`adapters/copilot_transcript_reader.py`),
não por request — limitação da fonte, documentada, não corrigida: espalhar tokens
retroativamente ao longo da sessão inventaria dados que a fonte não mede.

## Consequências

**Positivas:**
- Histórico completo (91.744 amostras) reproduzido no storage próprio e verificado byte-a-byte
  contra `SELECT SUM(...)` direto no SQLite, para as três fontes (claude-code, copilot, agy) —
  soma exata em todas as 4 dimensões de token.
- `go.sum` de 50 linhas; build rápido; nenhuma dependência de nuvem/k8s puxada por engano.
- O caminho de migração para "timeseries é a única fonte" fica claro para tudo, exceto a
  limitação abaixo.

**Negativas:**
- **A análise por sessão não tem para onde ir neste modelo.** `session_id`/`agent_id` ficam fora
  dos labels por cardinalidade, mas é exatamente por sessão que o dashboard hoje compara janelas
  de tempo (ex.: "sessão da manhã com uma skill vs. sessão da tarde sem", com precisão de
  segundo) — a funcionalidade mais usada do dashboard atual. Isso **bloqueia** a promessa de
  "timeseries será o único modelo no futuro" até essa lacuna ser resolvida. Resposta provável,
  não implementada aqui: essa granularidade pertence a um store de eventos/traces, não a um TSDB
  de métricas agregadas — precisaria de uma peça adicional (ex.: manter o SQLite, ou algo como
  Loki/Tempo) ao lado do modelo timeseries, não substituída por ele.
- Sem PromQL nativo local — consulta expressiva depende do VictoriaMetrics estar rodando.
- TSDB próprio + `/metrics` no mesmo processo é um padrão incomum comparado a exporters
  convencionais (que costumam ser sem estado). Registrado aqui para que não pareça acidental:
  existe porque o backfill histórico via `/metrics` é estruturalmente impossível.
- Duas implementações da normalização de evento (`core/model.py` em Python,
  `exporter/internal/metrics/series.go` em Go) podem divergir silenciosamente quando uma fonte
  nova entrar — sem um comando de verificação automatizado além da checagem manual feita no
  backfill inicial. Um subcomando `verify` (comparar somas por dia/modelo/fonte entre o storage e
  o SQLite) ficou fora do escopo desta primeira entrega e é candidato natural para uma iteração
  futura.
- `cwd`/`project` como label expõe paths absolutos do sistema de arquivos em `/metrics` — aceito
  porque o exporter só escuta em `127.0.0.1`, mesma postura do dashboard existente.
