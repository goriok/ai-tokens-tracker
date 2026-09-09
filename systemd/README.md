# Coleta contínua (systemd user units)

Instala services que rodam a coleta e os dashboards sozinhos, sem precisar lembrar de executar
comandos manualmente.

```bash
bash systemd/install-exporter.sh          # exporter Go: backfill + /metrics em :9464
bash systemd/install-victoriametrics.sh   # opcional: PromQL + vmui local em :8428, sem Docker
bash systemd/install-perses.sh            # opcional: dashboard versionado (perses/provisioning/), :8080
```

`ai-tokens-exporter.service` roda `bin/aitokensexporter` (backfilla uma vez, se ainda não feito;
depois serve `/metrics` continuamente em ciclos de 1min — cobre Claude Code, Copilot e a quota do
agy num único processo). `ai-tokens-victoriametrics.service` depende dele (`Wants=`/`After=`) mas
sobe mesmo se o exporter ainda não subiu — só o scrape falha até lá. `ai-tokens-perses.service`
depende do VictoriaMetrics do mesmo jeito, e lê os dashboards de `perses/provisioning/*.yaml`
neste repo (versionado, editável direto — sem passar pela UI).

VictoriaMetrics retém 60 dias (`retentionPeriod=60d`) — dado mais antigo some do vmui/Perses
sozinho, mas continua para sempre no storage do próprio exporter, reimportável a qualquer
momento com `cd exporter && go run ./cmd/aitokens-exporter export-vm`.

Os unit files ficam neste diretório (versionados no repo, não editados diretamente em
`~/.config/systemd/user/` — cada `install-*.sh` só symlinka).

## Comandos úteis

```bash
systemctl --user status ai-tokens-exporter.service
journalctl --user -u ai-tokens-exporter.service -f
curl http://127.0.0.1:9464/metrics
```

## Desinstalar

```bash
bash systemd/uninstall-exporter.sh
bash systemd/uninstall-victoriametrics.sh
bash systemd/uninstall-perses.sh
```

Para, desabilita e remove os symlinks — os dados coletados
(`~/.local/share/ai-tokens-tracker/tsdb/`, `.../vm-data/`, `perses/data/`) não são apagados, só
os units; `perses/provisioning/` nunca é tocado, é código versionado.

## Por quê

`systemctl --user` não precisa de root — opera inteiramente no `$HOME` do usuário (unit files em
`~/.config/systemd/user/`, sessão de D-Bus do próprio usuário).

Ver `docs/madrs/MADR-003` e `docs/madrs/MADR-004` para o racional completo.
