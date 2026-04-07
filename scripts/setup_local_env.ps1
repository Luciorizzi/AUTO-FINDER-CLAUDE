# Setup local environment para AutoFinder (Windows PowerShell)
# Uso: .\scripts\setup_local_env.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== AutoFinder - Setup Local ===" -ForegroundColor Cyan

# Verificar Python
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Python no encontrado. Instalar Python 3.11+" -ForegroundColor Red
    exit 1
}
Write-Host "Python: $pythonVersion" -ForegroundColor Green

# Crear virtual environment si no existe
if (-not (Test-Path ".venv")) {
    Write-Host "Creando virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
}

# Activar venv
Write-Host "Activando virtual environment..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1

# Instalar dependencias
Write-Host "Instalando dependencias..." -ForegroundColor Yellow
pip install -r requirements.txt

# Crear .env si no existe
if (-not (Test-Path ".env")) {
    Write-Host "Creando .env desde .env.example..." -ForegroundColor Yellow
    Copy-Item .env.example .env
}

# Crear carpeta data si no existe
if (-not (Test-Path "data")) {
    New-Item -ItemType Directory -Path "data" | Out-Null
}

# Inicializar DB
Write-Host "Inicializando base de datos..." -ForegroundColor Yellow
python -m scripts.init_db

# Smoke test
Write-Host "Ejecutando smoke test..." -ForegroundColor Yellow
python -m app.main

Write-Host "=== Setup completo ===" -ForegroundColor Green
