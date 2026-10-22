# Start backend (port 8000) and frontend (port 5173). Close the backend window to stop it.
# First run: install dependencies as described in README.md.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$activate = Join-Path $root "backend\.venv\Scripts\Activate.ps1"
$backendCmd = "cd `"$root\backend`"; if (Test-Path `"$activate`") { . `"$activate`" }; uvicorn app.main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd
Set-Location (Join-Path $root "frontend")
npm run dev
