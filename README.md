# Dashboard Launcher

One page (`localhost:9000`) to see, start, and stop the local dashboards.

## Run it

```powershell
.\run.ps1
```

## Adding a new app

Edit [`apps.yaml`](apps.yaml) — nothing else needs to change. No Python or
HTML edits, the page and API both read this file.

```yaml
- id: my-app          # used internally, keep it short and unique
  label: My App        # shown on the card
  open_port: 3000       # port the "Open" link jumps to
  processes:
    - cwd: MyApp         # folder, relative to Marco/
      cmd: ["MyApp/.venv/Scripts/python.exe", "-m", "uvicorn", "app:app", "--port", "3000"]
      port: 3000          # port the status check watches
      log: my-app.log      # written to launcher/logs/
```

- **Multiple processes per app** (like CB Pricer's backend + frontend): add
  more entries to `processes`. The card goes green only when all of them are
  up, and Start/Stop act on all of them together.
- **`health: http`** (default is `tcp`): use this instead of the plain port
  check for anything that accepts a connection before it's actually ready to
  serve — set `health_path` too if it's not `/`.
- **`env`**: a dict of extra environment variables for that process, if it
  needs config passed in rather than read from a file.
- Paths in `cwd` and any `cmd` token containing a slash are resolved relative
  to `Marco/` (the folder above this one). Bare tokens like `npm.cmd` are
  looked up on PATH as usual.

## How it works

- `config.py` — loads and validates `apps.yaml`.
- `process_control.py` — start/stop a process, check if it's up (TCP or
  HTTP), find a process by the port it's listening on.
- `app.py` — thin FastAPI layer: `/api/apps`, `/api/status`,
  `/api/start/{id}`, `/api/stop/{id}`. Serves `static/index.html` at `/`.
- `static/index.html` — fetches `/api/apps` once to build the cards, then
  polls `/api/status` every 3s. No app-specific code in here.

Stopping looks up *whatever process is currently listening on the configured
port* rather than remembering what it started — so Stop still works even if
you started something manually, or the launcher itself restarted.
