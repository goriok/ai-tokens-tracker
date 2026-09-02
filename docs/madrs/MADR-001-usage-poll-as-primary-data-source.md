# MADR-001: /usage polling como fonte primária, não a resposta de task calls

**Status:** approved

## Contexto

Objetivo: rastrear consumo de tokens do `agy` (Google Antigravity CLI) de forma leve, precisa e
sem custo adicional, cobrindo o uso real — que é majoritariamente via TUI interativa, não via
modo `-p`/print.

Investigação (ver histórico da sessão que originou esta decisão):

- O TUI mostra tokens na tela ("Thought for X, Y tokens") mas não persiste isso em nenhum
  arquivo legível — nem log de texto, nem JSON.
- O banco SQLite interno do `agy` (`~/.gemini/antigravity-cli/conversations/*.db`) grava
  metadados de geração em um blob protobuf não documentado — frágil e sujeito a quebrar em
  updates do produto, descartado como fonte.
- Não há integração oficial confirmável com LiteLLM ou qualquer proxy — a conta usada é
  assinatura via OAuth (keyring), sem hook de custom-provider/BYOK.
- `agy -p "<prompt>" --output-format json` expõe `usage` real por chamada, mas só cobre
  chamadas explícitas via `-p` — não o uso via TUI, que é a maioria do uso real.
- `agy -p "/usage" --output-format json` expõe a quota semanal restante por grupo de modelo
  (`remaining_fraction`, `reset_time`) como um comando **meta, com custo zero de token**
  (`usage.total_tokens: 0` na resposta) — e essa quota reflete **todo** o consumo da conta,
  TUI incluído, porque é o mesmo limite que a assinatura aplica independente de como a chamada
  foi feita.

## Decisão

`/usage` polling (via `AgyRunner.fetch_usage()`) é a fonte primária de dados de consumo —
snapshots periódicos (agendados via cron/systemd timer), com a diferença entre snapshots
sucessivos aproximando o consumo real no período, cobrindo TUI e `-p` igualmente.

`-p` com `--output-format json` (via `AgyRunner.run_task()`) continua disponível como fonte
secundária de **detalhe por tarefa** (tokens exatos de uma chamada específica, com label), útil
para automações/scripts que já chamam `agy -p` de qualquer forma — mas não é a fonte usada para
a baseline/gráfico geral, porque cobre só uma fração do uso real.

Nenhuma tentativa de decodificar o protobuf interno, nem qualquer forma de screen-scraping/OCR
da TUI — ambos rejeitados por serem frágeis e não alinhados com "leve, fácil, transparente,
adotável pelo time".

## Consequências

**Positivas:**
- Cobertura completa do consumo real (TUI + `-p`), sem custo de token para coletar.
- Sem dependência de mudar hábito de uso (TUI continua sendo o modo principal).
- Sem dependência de infraestrutura externa (proxy, servidor) nem de formato interno não
  documentado do `agy`.

**Negativas:**
- Granularidade limitada — `/usage` dá consumo agregado por grupo de modelo e janela semanal,
  não por tarefa individual. "Quantos tokens gastei nesta tarefa específica" só é respondível
  para chamadas feitas via `agy-track.py` (modo `-p`), não para uso via TUI.
- Se o `agy` mudar o formato de saída do comando `/usage` (schema `command.data.groups[].buckets[]`),
  a coleta quebra — mitigado por `fetch_usage()` já validar e falhar alto (`sys.exit(1)`) se a
  resposta não tiver o formato esperado, em vez de gravar dado inconsistente silenciosamente.
