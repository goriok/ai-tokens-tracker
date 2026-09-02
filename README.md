# agy-tracker

Rastreia o consumo de tokens/quota do Google Antigravity CLI (`agy`) — leve, sem custo de token
para coletar, cobrindo o uso via TUI (não só chamadas `-p`).

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

Dados em `~/.local/share/agy-tracker/usage.db` (SQLite; sobrescrevível via `$AGY_TOOL_DB`).

## Arquitetura

Hexagonal (ports & adapters — ver `docs/madrs/MADR-002`):

```
core/interfaces.py         # portas: UsageStore, AgyRunner
adapters/sqlite_usage_store.py   # único adapter de UsageStore hoje
adapters/agy_cli_runner.py       # único adapter de AgyRunner hoje
scripts/                   # aplicação — usa só as portas, nunca sqlite3/subprocess direto
```

## Instalação

### Standalone

```bash
bash install.sh   # symlinks bin/agystatus, bin/agysnapshot, bin/agywidget em ~/.local/bin/
```

### Como plugin do Claude Code

```
/plugin marketplace add goriok/agy-tracker
/plugin install agy-tracker
```

Registra a skill `agy-tracking` e os comandos `/agy-status`, `/agy-widget`.

### Como plugin do Antigravity (`agy`)

```bash
agy plugin install /path/to/agy-tracker/plugins/agy-tracker
# ou, a partir de um clone:
git clone git@github.com:goriok/agy-tracker.git
agy plugin install ./agy-tracker/plugins/agy-tracker
```

## Uso

```bash
agysnapshot   # registra um snapshot de quota agora (custo zero)
agystatus     # gera e abre o relatório HTML
agywidget     # widget GTK always-on-top (Linux)

python3 scripts/agy-track.py --model gemini-3.7-flash-low --task "revisão de PR" "revise este diff..."
```

Para coleta automática, agendar `agysnapshot` via cron ou systemd timer (ex. de hora em hora —
a quota é semanal, alta frequência não agrega muito).

## Limitações conhecidas

- `/usage` dá consumo agregado por grupo de modelo e janela semanal, não por tarefa individual.
  "Quantos tokens uma tarefa específica gastou" só é respondível para chamadas feitas via
  `agy-track.py`, não para uso via TUI.
- Se o `agy` mudar o schema de saída de `/usage`, a coleta falha alto (não grava dado
  inconsistente silenciosamente) — ver `AgyCliRunner.fetch_usage`.
