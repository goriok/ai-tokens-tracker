# MADRs — agy-as-tool

Decisões arquiteturais reais sobre este projeto — não notas de investigação, só decisões de
fato tomadas.

| MADR | Status | Resumo |
|---|---|---|
| [MADR-001](MADR-001-usage-poll-as-primary-data-source.md) | approved | `/usage` polling (custo zero, cobre TUI) como fonte primária; `-p` como detalhe secundário por tarefa |
| [MADR-002](MADR-002-hexagonal-ports-for-storage-and-cli-invocation.md) | approved | Portas `UsageStore`/`AgyRunner` para testabilidade, sem infraestrutura real |
