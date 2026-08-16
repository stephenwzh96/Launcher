# Dashboard launcher
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
Start-Process "http://localhost:9000"
& $python -m uvicorn app:app --app-dir $root --port 9000
