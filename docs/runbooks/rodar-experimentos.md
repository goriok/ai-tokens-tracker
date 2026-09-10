# Runbook: rodar um experimento comparativo

Procedimento para rodar uma rodada de experimento A/B (tool × estratégia × pergunta) usando o
script `.claude/workflows/rag-vs-manual-single-call.js` e a skill `experiment-design`, do
disparo até o report validado.

## Pré-requisitos

- Serviços rodando: `ai-tokens-exporter.service`, `ai-tokens-victoriametrics.service`,
  `ai-tokens-perses.service`.
- Skills `recall-search` e `confidence-analysis` registradas nas tools que vão participar da
  rodada (Claude Code e Copilot CLI carregam skills locais automaticamente; confirmar com
  `copilot skill list` se o Copilot CLI participar).

```bash
systemctl --user is-active ai-tokens-exporter.service ai-tokens-victoriametrics.service ai-tokens-perses.service
# active
# active
# active
```

## Passo 1 — Definir os parâmetros da rodada

Decidir antes de disparar:

- `questions`: lista de perguntas a comparar.
- `cwd`: diretório do projeto alvo.
- `contextDir`: diretório de contexto para a estratégia RAG/leitura direta.
- `recallCollection`: nome da collection do `recall-search` que cobre esse contexto.
- `roundPrefix`: data/hora da rodada, formato `YYYYMMDD-HHmm` (ex. `20260910-1000`).

## Passo 2 — Invocar o Workflow

Chamar a tool `Workflow` com `script: .claude/workflows/rag-vs-manual-single-call.js` e os
parâmetros do passo 1 em `args`:

```json
{
  "questions": ["pergunta 1", "pergunta 2"],
  "cwd": "/caminho/do/projeto",
  "contextDir": "/caminho/do/contexto",
  "recallCollection": "nome-da-collection",
  "roundPrefix": "20260910-1000"
}
```

O `Workflow` roda em background e notifica ao concluir.

Não fazer polling ativo — aguardar a notificação.

## Passo 3 — Ler o resultado

Ao concluir, ler o output da task (`rawOutput`, `validation.overallScore` e `validation.claims`
por item).

```bash
# a task notification traz o caminho do arquivo de output; ler com o Read tool
```

## Passo 4 — Confirmar os dados na store

Confirmar que o `session_name` de cada item da rodada aparece no VictoriaMetrics antes de seguir
para o report — uma falha silenciosa de propagação de label invalida a comparação sem erro
visível.

```bash
curl -s "http://127.0.0.1:8428/api/v1/label/session_name/values" | grep "<tool>-<estrategia>-<roundPrefix>"
```

Se algum `session_name` esperado não aparecer, investigar antes de prosseguir — não escrever o
report sobre dados incompletos.

## Passo 5 — Gerar o report

Invocar a skill `experiment-design` (`.claude/skills/experiment-design/SKILL.md`) para escrever
`docs/experiments/<nome-do-experimento>.md`, com contexto, grupos A/B, tabela de scores, link do
dashboard e achados.

## Passo 6 — Validar o report

```bash
# rodar sobre docs/experiments/<nome-do-experimento>.md
/goriok-skills:text-lint
/goriok-skills:canonical-terms
```

## Passo 7 — Visualizar no dashboard

Abrir `http://localhost:8080/projects/ai-tokens-tracker/dashboards/experiments` e preencher os
campos `Grupo A`/`Grupo B` com o `session_name` (ou padrão) de cada grupo da rodada.

## Troubleshooting

| Sintoma | Causa provável | Ação |
|---|---|---|
| `session_name` da rodada não aparece no VictoriaMetrics | Bug de propagação de label numa fonte específica (`copilot`/`agy`), ou export para VM não rodou | Checar `exporter/internal/metrics/series.go` para a fonte em questão; rodar `aitokens-exporter export-vm` manualmente |
| Item do `Workflow` falha com erro de safeguard da API (`[cyber]` ou similar) | Falso positivo do safeguard de segurança do modelo sobre um prompt técnico legítimo | Não é bug do experimento; reexecutar o item isolado se o dado for necessário, ou registrar como item ausente no report |
| Copilot CLI gasta tokens muito acima do esperado por chamada | MCP servers built-in (`github-mcp-server`) habilitados, ou agentes customizados não usados carregados em `~/.copilot/agents/` | Confirmar `--disable-builtin-mcps` está sendo aplicado (ver `--enable-builtin-mcps` em `aitokens-exporter track` se o experimento exige o oposto); limpar agentes não usados |
| Filtro `Grupo A`/`Grupo B` do dashboard não retorna nenhuma série | `session_name` digitado não bate com nenhum valor real, ou regex mal formado | Conferir valores reais com `curl http://127.0.0.1:8428/api/v1/label/session_name/values` |
| Serviço systemd do exporter/VictoriaMetrics/Perses inativo | Processo caiu ou não foi iniciado após reboot | `systemctl --user restart <serviço>`; conferir logs com `journalctl --user -u <serviço> -n 50` |

## Veja também

`.claude/skills/experiment-design/SKILL.md` — diretivas completas de desenho e nomenclatura.
`docs/madrs/MADR-003-timeseries-model-and-go-exporter.md` — modelo de dados por trás de
`session_name`.
