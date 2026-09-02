Launch the agy token usage GTK widget (always-on-top panel, Linux desktop only).

```bash
pkill -f "agy-widget-gtk.py" 2>/dev/null
sleep 1
/usr/bin/python3 "${CLAUDE_PLUGIN_ROOT}/scripts/agy-widget-gtk.py" &
sleep 2
WID=$(xdotool search --name "AGY-TOKENS" 2>/dev/null | head -1)
if [ -n "$WID" ]; then
    xprop -id "$WID" -f _NET_WM_STATE 32a -set _NET_WM_STATE "_NET_WM_STATE_ABOVE,_NET_WM_STATE_SKIP_TASKBAR,_NET_WM_STATE_SKIP_PAGER" 2>/dev/null
fi
```
