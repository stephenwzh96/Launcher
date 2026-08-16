"""Local launcher: start/stop/status for the dashboards listed in apps.yaml."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from config import check_paths, load_apps
from process_control import is_up, start_process, stop_process

HERE = Path(__file__).resolve().parent
LOG_DIR = HERE / "logs"
LOG_DIR.mkdir(exist_ok=True)

APPS = {a.id: a for a in load_apps(HERE / "apps.yaml")}

for warning in check_paths(list(APPS.values())):
    print(f"[launcher] WARNING: {warning}")

app = FastAPI()


def _get_app(app_id: str):
    if app_id not in APPS:
        raise HTTPException(status_code=404, detail=f"unknown app '{app_id}'")
    return APPS[app_id]


@app.get("/api/apps")
def list_apps():
    return [{"id": a.id, "label": a.label} for a in APPS.values()]


@app.get("/api/status")
def status():
    out = {}
    for app_id, cfg in APPS.items():
        states = [is_up(p) for p in cfg.processes]
        state = "up" if all(states) else "partial" if any(states) else "down"
        out[app_id] = {"label": cfg.label, "state": state, "open_port": cfg.open_port}
    return out


@app.post("/api/start/{app_id}")
def start(app_id: str):
    errors = [err for proc in _get_app(app_id).processes
              if (err := start_process(proc, LOG_DIR))]
    return {"ok": not errors, "errors": errors}


@app.post("/api/stop/{app_id}")
def stop(app_id: str):
    for proc in _get_app(app_id).processes:
        stop_process(proc)
    return {"ok": True}


app.mount("/", StaticFiles(directory=str(HERE / "static"), html=True), name="static")
