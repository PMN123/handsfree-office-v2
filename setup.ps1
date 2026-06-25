# HandsFree Office - server bootstrap (PRD D3, section 8.6).
# Installs Ollama + the local NLU model and the Python dependencies.
# Local-only: no cloud, no API keys. Run once before first use:
#     powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
$Here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Model = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { "qwen2.5:3b-instruct" }
$Py    = if ($env:PYTHON) { $env:PYTHON } else { "python" }

Write-Host "==> HandsFree Office setup"

# 1) Install Ollama if absent.
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "==> Ollama already installed"
} else {
    Write-Host "==> Installing Ollama via winget..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
    } else {
        Write-Error "winget not found. Install Ollama from https://ollama.com/download then re-run."
        exit 1
    }
}

# 2) Make sure the Ollama service is reachable, then pull the model.
function Test-Ollama {
    try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:11434/api/tags -TimeoutSec 2 | Out-Null; return $true }
    catch { return $false }
}
if (-not (Test-Ollama)) {
    Write-Host "==> Starting Ollama service..."
    Start-Process -WindowStyle Hidden ollama -ArgumentList "serve"
    for ($i = 0; $i -lt 15; $i++) { if (Test-Ollama) { break }; Start-Sleep -Seconds 1 }
}

Write-Host "==> Pulling model: $Model  (one-time, multi-GB download)"
ollama pull $Model

# 3) Python dependencies.
Write-Host "==> Installing Python dependencies"
& $Py -m pip install -r (Join-Path $Here "server\requirements.txt")

Write-Host ""
Write-Host "==> Done. Start the server with:"
Write-Host "      $Py $Here\server\server.py"
