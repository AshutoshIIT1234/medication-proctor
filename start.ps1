[CmdletBinding()]
param(
  [switch]$NoInstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Ensure-Tool($name, $installHint) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    Write-Error "Required tool '$name' not found in PATH. $installHint"
  }
}

Write-Host "== Medication Proctor: One-Command Dev Start ==" -ForegroundColor Cyan

# Check tools
Ensure-Tool 'uv' "Install uv: https://docs.astral.sh/uv/getting-started/installation/"
Ensure-Tool 'npm' "Install Node.js 18+: https://nodejs.org/"
Ensure-Tool 'python' "Install Python 3.13: https://www.python.org/downloads/"

# .env sanity
if (-not (Test-Path '.env')) {
  Write-Error "Missing .env at repo root. Copy .env.example and fill credentials."
}

# Python deps
if (-not $NoInstall) {
  Write-Host "Syncing Python deps with uv..." -ForegroundColor Yellow
  uv sync
}

# Frontend env setup from root .env (Stream keys only)
$frontendEnv = Join-Path 'frontend' '.env.local'
if (-not (Test-Path $frontendEnv)) {
  Write-Host "Creating frontend/.env.local from root .env (Stream keys only)..." -ForegroundColor Yellow
  $rootEnv = Get-Content '.env'
  $streamApiKey = ($rootEnv | Where-Object { $_ -match '^STREAM_API_KEY=' }) -replace '^STREAM_API_KEY=', ''
  $streamApiSecret = ($rootEnv | Where-Object { $_ -match '^STREAM_API_SECRET=' }) -replace '^STREAM_API_SECRET=', ''
  if (-not $streamApiKey -or -not $streamApiSecret) {
    Write-Warning "STREAM_API_KEY/STREAM_API_SECRET not found in .env; frontend /api/token route may fail."
  }
  @"`nNEXT_PUBLIC_STREAM_API_KEY=$streamApiKey`nSTREAM_API_SECRET=$streamApiSecret`n"@ | Set-Content -NoNewline $frontendEnv
}

# Frontend deps
if (-not $NoInstall) {
  Push-Location frontend
  try {
    if (-not (Test-Path 'node_modules')) {
      Write-Host "Installing frontend deps..." -ForegroundColor Yellow
      npm install
    }
  } finally { Pop-Location }
}

Write-Host "Launching backend (8000) and frontend (3000) in separate terminals..." -ForegroundColor Green

$root = Get-Location
$backend = Start-Process -PassThru powershell -WorkingDirectory $root -ArgumentList @('-NoExit','-Command','uv run python main.py serve --host 127.0.0.1 --port 8000')
$frontend = Start-Process -PassThru powershell -WorkingDirectory (Join-Path $root 'frontend') -ArgumentList @('-NoExit','-Command','npm run dev')

Write-Host "Backend:  http://127.0.0.1:8000"
Write-Host "Frontend: http://localhost:3000"
