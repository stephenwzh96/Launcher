# Dashboard launcher: starts the local service (if not already running) and opens the page.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'

$listening = Get-NetTCPConnection -LocalPort 9000 -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
    Start-Process -WindowStyle Hidden -FilePath $python `
        -ArgumentList @('-m', 'uvicorn', 'app:app', '--app-dir', $root, '--port', '9000') `
        -WorkingDirectory $root
    Start-Sleep -Seconds 1
}

Start-Process "http://localhost:9000"
