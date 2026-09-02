# ai-tokens-tracker

Rastreia o consumo de tokens/quota de agentes de IA — leve, sem custo de token para coletar.

Hoje cobre o Google Antigravity CLI (`agy`), cobrindo o uso via TUI (não só chamadas `-p`).
Outros agentes (Claude Code, hermes) estão planejados — ver "Limitações conhecidas" e a
arquitetura hexagonal abaixo, pensada para receber um novo `AgentRunner` por agente sem reescrever
o resto do pipeline.

Ver `docs/madrs/` para o racional completo (por que `/usage` polling e não outras fontes
consideradas — protobuf interno, LiteLLM, screen-scraping — todas rejeitadas).

## Como funciona

- `scripts/agy-snapshot.py` — roda `agy -p "/usage" --output-format json` (custo **zero** de
  token, é um comando meta) e grava a quota semanal restante por grupo de modelo no SQLite.
  Pensado para rodar em cron/timer, ex. de hora em hora.
- `scripts/agy-track.py` — wrapper opcional de `agy -p` para tarefas específicas: registra
  tokens exatos daquela chamada, com um label.
- `scripts/agy-report.py` — gera um HTML standalone (Chart.js via CDN, sem servidor) com os
  dados coletados.
- `scripts/agy-widget-gtk.py` — widget GTK3 always-on-top (Linux desktop), mostra quota atual
  e chamadas rastreadas do dia.
- `scripts/agy-delegate.py` — roda uma tarefa via `agy -p`, escolhendo o modelo automaticamente
  por complexidade (`--complexity low|medium|high`) + quota semanal restante (ver
  `core/model_policy.py`), registrando o resultado como uma chamada rastreada.

Dados em `~/.local/share/ai-tokens-tracker/usage.db` (SQLite; sobrescrevível via `$AGY_TOOL_DB`).

## Arquitetura

Hexagonal (ports & adapters — ver `docs/madrs/MADR-002`):

```
core/interfaces.py         # portas: UsageStore, AgyRunner
adapters/sqlite_usage_store.py   # único adapter de UsageStore hoje
adapters/agy_cli_runner.py       # único adapter de AgyRunner hoje — outros agentes viram novos adapters
scripts/                   # aplicação — usa só as portas, nunca sqlite3/subprocess direto
```

## Instalação

### Standalone

```bash
bash install.sh   # symlinks bin/agystatus, bin/agysnapshot, bin/agywidget, bin/agydelegate em ~/.local/bin/
```

### Como plugin do Claude Code

```
/plugin marketplace add goriok/ai-tokens-tracker
/plugin install ai-tokens-tracker
```

Registra a skill `agy-tracking` e os comandos `/agy-status`, `/agy-widget`.

### Como plugin do Antigravity (`agy`)

```bash
agy plugin install /path/to/ai-tokens-tracker/plugins/ai-tokens-tracker
# ou, a partir de um clone:
git clone git@github.com:goriok/ai-tokens-tracker.git
agy plugin install ./ai-tokens-tracker/plugins/ai-tokens-tracker
```

## Uso

```bash
agysnapshot   # registra um snapshot de quota agora (custo zero)
agystatus     # gera e abre o relatório HTML
agywidget     # widget GTK always-on-top (Linux)
agydelegate --complexity low --task "revisão de PR" "revise este diff..."

python3 scripts/agy-track.py --model gemini-3.7-flash-low --task "revisão de PR" "revise este diff..."
```

Para coleta automática, agendar `agysnapshot` via cron ou systemd timer (ex. de hora em hora —
a quota é semanal, alta frequência não agrega muito).

## Limitações conhecidas

- Só cobre o `agy` (Google Antigravity CLI) hoje — os nomes de comando (`agystatus`,
  `agysnapshot`, `agywidget`, `agydelegate`) e o schema de dados ainda são específicos dele.
  Suporte a outros agentes é planejado, sem data definida.
- `/usage` dá consumo agregado por grupo de modelo e janela semanal, não por tarefa individual.
  "Quantos tokens uma tarefa específica gastou" só é respondível para chamadas feitas via
  `agy-track.py`, não para uso via TUI.
- Se o `agy` mudar o schema de saída de `/usage`, a coleta falha alto (não grava dado
  inconsistente silenciosamente) — ver `AgyCliRunner.fetch_usage`.
