# ai-tokens-tracker

[![CI](https://github.com/goriok/ai-tokens-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/goriok/ai-tokens-tracker/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/goriok/ai-tokens-tracker/branch/main/graph/badge.svg)](https://codecov.io/gh/goriok/ai-tokens-tracker)

Rastreia o consumo de tokens/quota de agentes de IA — leve, sem custo de token para coletar.

Cobre hoje o Google Antigravity CLI (`agy`, incluindo uso via TUI, não só chamadas `-p`), o
Claude Code (via transcripts locais) e o Copilot CLI (via session-state local). Um único binário
Go (`aitokens-exporter`) lê essas fontes direto, mantém um modelo de séries temporais local e
expõe `/metrics` no formato Prometheus. Ver `docs/madrs/` para o racional completo das decisões
(por que `/usage` polling, por que timeseries em vez de SQLite, por que Go em vez de Python).

## Como funciona

- `exporter/internal/adapters/claudecode` — lê `~/.claude/projects/**/*.jsonl` recursivamente
  (transcripts locais já escritos pelo Claude Code, custo **zero** de token). Incremental via
  cursor de byte offset por arquivo. Inclui subagentes (`subagents/**/*.jsonl`) — compartilham o
  `session_id` da conversa que os lançou, mas carregam um `agent_id` distinto
  (`isSidechain: true` no transcript).
- `exporter/internal/adapters/copilot` — lê `~/.copilot/session-state/**/events.jsonl` (custo
  **zero**), um evento por sessão completada (`session.shutdown`). Lê também `workspace.yaml`
  para o título da sessão.
- `exporter/internal/adapters/agycli` — roda `agy -p "/usage" --output-format json` (custo
  **zero**, é um comando meta) para a quota semanal restante por grupo de modelo. `RunAgyTask`
  roda uma tarefa real via `agy -p` (custo real) para chamadas rastreadas.
- `exporter/internal/adapters/tracker` — roda uma tarefa real via `copilot -p` (custo real) para
  chamadas rastreadas do Copilot.
- `exporter/internal/modelpolicy` — escolhe modelo automaticamente por complexidade + quota
  semanal restante, usado por `delegate`.

Dados em `~/.local/share/ai-tokens-tracker/tsdb/` (log append-only próprio, não SQLite — ver
`docs/madrs/MADR-003`).

## Testes

```bash
cd exporter && go test ./...
```

## Arquitetura

Hexagonal (ports & adapters — ver `docs/madrs/MADR-002` para o racional original, hoje
implementado em Go, e `docs/madrs/MADR-004` para a migração):

```
exporter/internal/ports/                    # portas: ClaudeCodeTranscriptReader, CopilotTranscriptReader, QuotaRunner
exporter/internal/model/                    # domínio: ClaudeCodeEvent, CopilotEvent, TaskCall, UsageSnapshot
exporter/internal/adapters/claudecode/      # único adapter de ClaudeCodeTranscriptReader hoje
exporter/internal/adapters/copilot/         # único adapter de CopilotTranscriptReader hoje
exporter/internal/adapters/agycli/          # único adapter de QuotaRunner hoje; também RunAgyTask
exporter/internal/adapters/tracker/         # RunCopilotTask (chamada rastreada real)
exporter/internal/ingest/                   # Backfill/Incremental — orquestra os readers -> metrics -> tsdbstore
exporter/internal/metrics/                  # mapeia eventos de domínio em séries Prometheus
exporter/internal/tsdbstore/                # storage próprio (append-only), única fonte de verdade histórica
exporter/internal/httpapi/                  # /metrics, /-/healthy
exporter/cmd/aitokens-exporter/             # CLI: backfill, serve, track, delegate, export-vm
```

Um agente novo (hermes, opencode) vira um adapter novo (porta existente ou nova, conforme o tipo
de dado que ele expõe) — sem reescrever `ingest/` nem `metrics/`.

## Instalação

### Coleta contínua + dashboards (recomendado)

```bash
bash systemd/install-exporter.sh          # backfilla o histórico e sobe /metrics em :9464
bash systemd/install-victoriametrics.sh   # opcional: PromQL + vmui local em :8428, sem Docker
                                           # (já importa o histórico automaticamente ao instalar)
bash systemd/install-perses.sh            # opcional: dashboard versionado (perses/provisioning/)
                                           # em :8080, requer o VictoriaMetrics acima
```

Ver `systemd/README.md` para detalhes de cada unit.

### Comandos manuais (chamadas rastreadas)

```bash
bash install.sh   # symlinks bin/agydelegate, bin/agytrack, bin/copilottrack em ~/.local/bin/
```

### Como plugin do Claude Code

```
/plugin marketplace add goriok/ai-tokens-tracker
/plugin install ai-tokens-tracker
```

Registra a skill `agy-tracking`.

**Atualizar:** `/plugin marketplace update goriok/ai-tokens-tracker`, seguido de `/reload-plugins`
para o Claude Code recarregar o conteúdo novo — sem o reload, o autocomplete de slash command
continua mostrando a versão em cache.

### Como plugin do Antigravity (`agy`)

```bash
agy plugin install /path/to/ai-tokens-tracker/plugins/ai-tokens-tracker
# ou, a partir de um clone:
git clone git@github.com:goriok/ai-tokens-tracker.git
agy plugin install ./ai-tokens-tracker/plugins/ai-tokens-tracker
```

`plugins/ai-tokens-tracker/skills/` é um symlink para `../../skills` (a mesma pasta que o Claude
Code usa) — uma única fonte, sem duplicar conteúdo entre os dois formatos.

**Atualizar:** `git pull` no clone, depois `agy plugin install ./ai-tokens-tracker/plugins/ai-tokens-tracker`
de novo — sobrescreve o registro anterior em `~/.gemini/config/plugins/ai-tokens-tracker/`. Não
existe `agy plugin update`; instalar de novo é o mecanismo de atualização. `agy plugin validate
./ai-tokens-tracker/plugins/ai-tokens-tracker` confirma que a pasta está bem formada antes de
instalar.

## Uso

```bash
agydelegate --complexity low --task "revisão de PR" "revise este diff..."
agytrack --model gemini-3.7-flash-low --task "revisão de PR" "revise este diff..."
copilottrack --model auto --task "revisão de PR" "revise este diff..."
```

Cada comando cai em `go run` automaticamente se o binário não estiver instalado ainda —
`cd exporter && make install` evita esse overhead a cada chamada.

## Modelo de séries temporais

```bash
curl http://127.0.0.1:9464/metrics                                              # estado corrente, formato Prometheus
xdg-open http://127.0.0.1:8428/vmui/                                            # PromQL ad-hoc
xdg-open http://127.0.0.1:8080/projects/ai-tokens-tracker/dashboards/ai-tokens     # visão geral de uso
xdg-open http://127.0.0.1:8080/projects/ai-tokens-tracker/dashboards/experiments   # comparação A/B por sessão
# exemplo de query: sum(increase(aitokens_tokens_total[7d])) by (source)
```

O dashboard `experiments` compara consumo de token entre sessões nomeadas (`claude -n <nome>`) —
pensado para os experimentos rag-vs-manual em `.claude/workflows/`. Dois seletores multi-valor
(grupo A / grupo B); a comparação é por seleção manual das sessões, não agrupamento automático por
regex, porque a nomenclatura de sessão não é consistente entre execuções passadas.

**Importante sobre histórico:** o VictoriaMetrics só "vê" o instante do scrape (`/metrics` não
carrega timestamp — ver MADR-003). Para o vmui mostrar a evolução real ao longo das semanas, é
preciso importar explicitamente com os timestamps originais — `install-victoriametrics.sh` já
faz isso na instalação; rodar de novo manualmente após um backfill maior:

```bash
cd exporter && go run ./cmd/aitokens-exporter export-vm
```

## Limitações conhecidas

- Cobre `agy`, Claude Code e Copilot hoje — outros agentes (hermes, opencode) são planejados,
  sem data definida.
- `/usage` do agy dá consumo agregado por grupo de modelo e janela semanal, não por tarefa
  individual. "Quantos tokens uma tarefa específica gastou" só é respondível para chamadas
  feitas via `agytrack`/`agydelegate`, não para uso via TUI — investigado em 2026-09: `agy` não
  grava tokens por sessão em nenhum arquivo local (`~/.gemini/antigravity-cli/history.jsonl` só
  tem o prompt digitado; `brain/<id>/.system_generated/logs/transcript*.jsonl` registra passos
  (thinking/tool_calls) sem contagem de tokens; `log/*.log` só tem log de execução de CLI) —
  diferente do Claude Code, cujo transcript `.jsonl` sempre inclui `usage` por request.
- Se o `agy` mudar o schema de saída de `/usage`, a coleta falha alto (não grava dado
  inconsistente silenciosamente) — ver `agycli.Runner.FetchQuota`.
- **Sem análise ad-hoc por sessão/janela de tempo arbitrária** — o dashboard HTML que oferecia
  isso foi removido junto com o SQLite (ver `docs/madrs/MADR-004`). `session_name` (sessões
  nomeadas via `claude -n <nome>`) cobre comparação A/B nomeada no dashboard `experiments`, mas
  não substitui a comparação livre por timestamp que existia antes.
