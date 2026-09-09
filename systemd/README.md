# Coleta contínua (systemd user units)

Instala timers/services que rodam a coleta e o dashboard sozinhos, sem precisar lembrar de
executar os comandos manualmente.

```bash
bash systemd/install.sh
```

Instala e ativa:

- `ai-tokens-claude-code.timer` — roda `claude-code-snapshot.py` a cada 5min (custo zero de
  token, leitura incremental de arquivo local).
- `ai-tokens-agy.timer` — roda `agy-snapshot.py` a cada 1h (a quota é semanal, mais frequência
  não agrega — mas diferente do timer acima, essa chamada sobe o processo `agy` de verdade).
- `ai-tokens-dashboard.service` — sobe `token_dashboard_server.py` (FastAPI, via `uv run`) como
  processo permanente em `http://127.0.0.1:8765`, reinicia sozinho se cair
  (`Restart=on-failure`).

Os unit files ficam neste diretório (versionados no repo, não editados diretamente em
`~/.config/systemd/user/` — `install.sh` só symlinka).

## Comandos úteis

```bash
systemctl --user status ai-tokens-dashboard.service
journalctl --user -u ai-tokens-dashboard.service -f
systemctl --user list-timers --all | grep ai-tokens
```

## Desinstalar

```bash
bash systemd/uninstall.sh
```

Para, desabilita e remove os symlinks — os arquivos originais continuam no repo.

## Por quê

`systemctl --user` não precisa de root — opera inteiramente no `$HOME` do usuário (unit files em
`~/.config/systemd/user/`, sessão de D-Bus do próprio usuário).

## Exporter de séries temporais (opcional, separado)

Scripts à parte, opt-in — instalar `install.sh` acima não instala nada disto:

```bash
bash systemd/install-exporter.sh          # exporter Go: backfill + /metrics em :9464
bash systemd/install-victoriametrics.sh   # opcional: VictoriaMetrics local, scrapeia o exporter, :8428
bash systemd/install-perses.sh            # opcional: dashboard versionado (perses/provisioning/), :8080
```

`ai-tokens-exporter.service` roda `bin/aitokensexporter` (backfilla uma vez, se ainda não feito;
depois serve `/metrics` continuamente). `ai-tokens-victoriametrics.service` depende dele
(`Wants=`/`After=`) mas sobe mesmo se o exporter ainda não subiu — só o scrape falha até lá.
`ai-tokens-perses.service` depende do VictoriaMetrics do mesmo jeito, e lê os dashboards de
`perses/provisioning/*.yaml` neste repo (versionado, editável direto — sem passar pela UI).

VictoriaMetrics retém 60 dias (`retentionPeriod=60d`) — dado mais antigo some do vmui/Perses
sozinho, mas continua para sempre no storage do próprio exporter, reimportável a qualquer
momento com `cd exporter && go run ./cmd/aitokens-exporter export-vm`.

Desinstalar cada um com `uninstall-exporter.sh`/`uninstall-victoriametrics.sh`/`uninstall-perses.sh`
— os dados coletados (`~/.local/share/ai-tokens-tracker/tsdb/`, `.../vm-data/`,
`perses/data/`) não são apagados, só os units; `perses/provisioning/` nunca é tocado, é código
versionado. Ver `docs/madrs/MADR-003` para o racional.
