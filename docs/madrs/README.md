# MADRs — agy-as-tool

Decisões arquiteturais reais sobre este projeto — não notas de investigação, só decisões de
fato tomadas.

| MADR | Status | Resumo |
|---|---|---|
| [MADR-001](MADR-001-usage-poll-as-primary-data-source.md) | approved | `/usage` polling (custo zero, cobre TUI) como fonte primária; `-p` como detalhe secundário por tarefa |
| [MADR-002](MADR-002-hexagonal-ports-for-storage-and-cli-invocation.md) | superseded | Portas `UsageStore`/`AgyRunner` (Python) para testabilidade — ver MADR-004 |
| [MADR-003](MADR-003-timeseries-model-and-go-exporter.md) | approved | Exporter Go com TSDB próprio (não `prometheus/tsdb`, revertido por peso) + `/metrics`, VictoriaMetrics local via scrape |
| [MADR-004](MADR-004-remove-python-sqlite-only-go.md) | approved | Remoção do Python/SQLite/dashboard HTML — Go (ports/adapters) como única fonte |
