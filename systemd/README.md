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
