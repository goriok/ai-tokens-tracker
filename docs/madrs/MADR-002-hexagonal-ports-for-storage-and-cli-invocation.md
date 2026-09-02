# MADR-002: Portas UsageStore e AgyRunner (hexagonal)

**Status:** approved

## Contexto

Mesmo racional do MADR-001 do projeto `recall` (`goriok/recall`): hoje existe só um backend de
persistência (SQLite) e um jeito de invocar o `agy` (subprocess do binário real) — sem um
segundo adapter real à vista para nenhum dos dois. Pela referência de design hexagonal usada
neste workspace (Cockburn, Ports & Adapters), isso normalmente seria motivo para não extrair
porta ainda.

A motivação aqui, como no `recall`, é testabilidade sem infraestrutura real — testar
`agy-snapshot.py`/`agy-track.py`/`agy-report.py` sem depender do binário `agy` de verdade
(rede, autenticação, custo/quota) nem de um arquivo SQLite real em disco.

## Decisão

- `core/model.py` — dataclasses de domínio: `UsageSnapshot`, `TaskCall`, `AgyRunResult`.
- `core/interfaces.py` — portas: `UsageStore` (`record_snapshot`, `record_task_call`,
  `list_snapshots`, `list_task_calls`) e `AgyRunner` (`fetch_usage`, `run_task`).
- `adapters/sqlite_usage_store.py` — `SqliteUsageStore`, único adapter de `UsageStore` hoje.
- `adapters/agy_cli_runner.py` — `AgyCliRunner`, único adapter de `AgyRunner` hoje.
- Os três scripts de aplicação (`scripts/agy-snapshot.py`, `agy-track.py`, `agy-report.py`)
  instanciam os adapters concretos e usam só através da porta — nenhum deles importa
  `sqlite3`/`subprocess` diretamente.

## Consequências

**Positivas:** um fake de `UsageStore`/`AgyRunner` habilita testar os três scripts sem rede nem
disco real. Um segundo backend (ex.: Postgres compartilhado, se o time quiser dashboard central
no futuro) se encaixa sem tocar nos scripts de aplicação.

**Negativas:** indireção a mais para um projeto ainda pequeno — aceito conscientemente pelo
motivo de testabilidade, não por variação de tecnologia em vista.
