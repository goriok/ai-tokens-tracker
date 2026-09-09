# MADR-004: remoção do Python/SQLite/dashboard HTML — Go como única fonte

**Status:** approved

## Contexto

MADR-003 introduziu o modelo timeseries em **coexistência** deliberada: o SQLite Python
(`adapters/sqlite_usage_store.py`) continuava sendo a fonte de verdade, o dashboard HTML
(`scripts/token_dashboard_server.py`) continuava funcionando, e o exporter Go lia o `usage.db`
que o Python escrevia — aditivo, não substituição. MADR-003 registrou explicitamente uma
consequência negativa bloqueando a promessa de "timeseries vira o único modelo": a análise por
sessão com precisão de segundo, a funcionalidade mais usada do dashboard, não tinha equivalente
no modelo de métricas agregadas (`session_id`/`agent_id` ficam fora dos labels por cardinalidade).

Decisão de produto (do usuário, não deste MADR): remover o dashboard HTML e o SQLite mesmo assim,
aceitando essa perda conscientemente — `session_name` (ver MADR-003, adicionado depois da
decisão inicial) cobre o caso de uso real de comparação nomeada (`claude -n <nome>`, usado pelos
experimentos rag-vs-manual), e a comparação ad-hoc por janela de tempo arbitrária deixa de
existir como feature.

## Decisão

Removidos por completo: `core/`, `adapters/`, `scripts/`, `tests/` (Python), `pyproject.toml`,
`uv.lock`, o job `test` do CI, os units systemd `ai-tokens-claude-code.*`, `ai-tokens-agy.*`,
`ai-tokens-dashboard.service`, e os comandos `bin/agystatus`, `agysnapshot`, `agywidget`,
`claudecodesnapshot`, `copilotsnapshot`, `tokendashboard` (sem equivalente Go — a coleta agora é
contínua via `ai-tokens-exporter.service`, não pontual por comando).

O que substituiu cada peça, com o mesmo princípio hexagonal (ports & adapters) do MADR-002,
agora em Go:

| Python removido | Equivalente Go |
|---|---|
| `adapters/claude_code_transcript_reader.py` | `exporter/internal/adapters/claudecode` |
| `adapters/copilot_transcript_reader.py` | `exporter/internal/adapters/copilot` |
| `adapters/agy_cli_runner.py` (`fetch_usage`) | `exporter/internal/adapters/agycli` (`FetchQuota`) |
| `adapters/agy_cli_runner.py` (`run_task`) | `exporter/internal/adapters/agycli` (`RunAgyTask`) |
| `adapters/copilot_cli_runner.py` | `exporter/internal/adapters/tracker` (`RunCopilotTask`) |
| `adapters/sqlite_usage_store.py` | `exporter/internal/tsdbstore` (já existia desde MADR-003) |
| `core/model.py`, `core/interfaces.py` | `exporter/internal/model`, `exporter/internal/ports` |
| `core/model_policy.py` | `exporter/internal/modelpolicy` |
| `scripts/agy-snapshot.py`, `claude-code-snapshot.py`, `copilot-snapshot.py` | `aitokens-exporter serve` (loop contínuo, não mais 3 timers separados) |
| `scripts/agy-track.py` | `aitokens-exporter track --tool agy` (`bin/agytrack`) |
| `scripts/copilot-track.py` | `aitokens-exporter track --tool copilot` (`bin/copilottrack`) |
| `scripts/agy-delegate.py` | `aitokens-exporter delegate` (`bin/agydelegate`) |
| `scripts/token_dashboard_server.py` | Perses (`perses/provisioning/dashboard.yaml`) + vmui — sem equivalente 1:1, ver Consequências |
| `scripts/agy-report.py`, `agy-widget-gtk.py` | sem equivalente — HTML standalone e widget GTK não portados |

Todos os adapters Go foram construídos via TDD (ver `mattpocock-skills:tdd`) e validados ao vivo
contra dados/binários reais antes de qualquer remoção — não só contra fixtures. Dois bugs reais
foram pegos nesse processo, não em produção:

- **claudecode**: a linha `custom-title` é reescrita no transcript a cada save de sessão, não
  uma vez — real na conta: 8.954 linhas brutas para 160 títulos únicos. O SQLite Python nunca
  expôs isso porque `record_session_title` era um upsert; sem banco, o reader precisou de dedup
  explícito (último valor vence).
- **agycli**: `RunAgyTask` não tinha timeout de subprocess — uma chamada real a um modelo com
  quota semanal esgotada travou por 15+ minutos durante a verificação ao vivo. O Python tinha
  `subprocess.run(..., timeout=600)`; o port inicial não. Corrigido com timeout por chamada
  (`context.WithTimeout`), provado por um teste que mata um `sleep 10` real em 100ms.

A ingestão completa (claude-code + copilot + quota) foi refeita do zero contra os dados reais da
conta após a reescrita, sem depender do SQLite em nenhum ponto — 137.246+ amostras, os totais de
token batendo com uma re-soma independente feita direto sobre os transcritos brutos.

## Consequências

**Positivas:**
- Um único binário (`aitokens-exporter`) e um runtime (Go) para todo o pipeline — sem `uv`,
  sem `.venv`, sem `fastapi`/`uvicorn` só para servir uma página HTML.
- Coleta contínua (`serve`, ciclo de 1min) substitui três timers systemd separados rodando em
  cadências diferentes (5min, 1h) que nunca cobriam Copilot de verdade (não havia timer para
  ele — lacuna já registrada informalmente antes deste MADR).
- Ports/adapters (hexagonal) preservados como princípio de design, não perdidos na tradução.

**Negativas — aceitas conscientemente, não resolvidas:**
- **A lacuna de análise por sessão que o MADR-003 previu se concretiza.** Não há mais nenhuma
  superfície (dashboard ou outra) para comparar duas janelas de tempo arbitrárias por
  `session_id` com precisão de segundo. `session_name` cobre o caso de uso real que motivou essa
  decisão (comparação A/B nomeada, ver `perses/provisioning/dashboard-experiments.yaml`), mas
  uma sessão sem título perde a granularidade que o dashboard antigo dava de graça.
- `scripts/agy-report.py` (relatório HTML standalone, sem servidor) e `scripts/agy-widget-gtk.py`
  (widget desktop always-on-top) não têm equivalente — quem dependia deles perde a
  funcionalidade sem substituto. Nenhum uso ativo identificado no momento da remoção; revisitar
  se isso se mostrar necessário.
- Histórico do SQLite (`usage.db`, incluindo os 44 snapshots de quota já coletados e o histórico
  de `task_calls`) não foi migrado para o storage do exporter antes da remoção — o storage do
  exporter começou sua própria linha do tempo a partir da última reescrita completa (Fase de
  integração ao `ingest`, ver commits anteriores), com backfill dos transcritos ainda existentes
  em disco, não da própria base de dados SQLite.
