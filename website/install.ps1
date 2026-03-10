# VexNet Installer for Windows
# Run: irm https://vexnet.ai/install.ps1 | iex
# Or: powershell -ExecutionPolicy Bypass -File install-windows.ps1

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "     VexNet Installer for Windows       " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$VEX_DIR = "$env:USERPROFILE\.vex"
$INSTALL_DIR = "$VEX_DIR\app"
$VENV_DIR = "$VEX_DIR\venv"

# ─── Step 1: Check Python ───
Write-Host "[1/5] Checking Python..." -ForegroundColor Yellow

$python = $null
foreach ($cmd in @("python3", "python", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 12) {
                $python = $cmd
                Write-Host "  Found: $ver" -ForegroundColor Green
                break
            }
        }
    } catch {}
}

if (-not $python) {
    Write-Host ""
    Write-Host "  Python 3.12+ is required but not found." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Install Python from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "  Make sure to check 'Add Python to PATH' during install." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# ─── Step 2: Check/Install Ollama ───
Write-Host "[2/5] Checking Ollama..." -ForegroundColor Yellow

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollama) {
    Write-Host "  Ollama is installed." -ForegroundColor Green
} else {
    Write-Host "  Ollama not found. Installing..." -ForegroundColor Yellow

    $ollamaUrl = "https://ollama.com/download/OllamaSetup.exe"
    $ollamaInstaller = "$env:TEMP\OllamaSetup.exe"

    Write-Host "  Downloading Ollama..."
    Invoke-WebRequest -Uri $ollamaUrl -OutFile $ollamaInstaller -UseBasicParsing

    Write-Host "  Running Ollama installer (follow the prompts)..."
    Start-Process -FilePath $ollamaInstaller -Wait

    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollama) {
        Write-Host "  Ollama installed but not in PATH. You may need to restart your terminal." -ForegroundColor Yellow
        Write-Host "  After restarting, run this installer again." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "  Ollama installed successfully!" -ForegroundColor Green
}

# ─── Step 3: Pull Ollama models ───
Write-Host "[3/5] Setting up AI models..." -ForegroundColor Yellow

# Start Ollama if not running
$ollamaRunning = Get-Process ollama -ErrorAction SilentlyContinue
if (-not $ollamaRunning) {
    Write-Host "  Starting Ollama..."
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

Write-Host "  Pulling language model (this may take a few minutes)..."
& ollama pull glm4:latest 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Trying alternative model..."
    & ollama pull llama3.2:latest 2>&1 | Out-Null
}
Write-Host "  Language model ready." -ForegroundColor Green

Write-Host "  Pulling embedding model..."
& ollama pull nomic-embed-text:latest 2>&1 | Out-Null
Write-Host "  Embedding model ready." -ForegroundColor Green

# ─── Step 4: Install VexNet ───
Write-Host "[4/5] Installing VexNet..." -ForegroundColor Yellow

# Create install directory
New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null

# Create virtual environment
Write-Host "  Creating Python environment..."
& $python -m venv $VENV_DIR
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Failed to create virtual environment." -ForegroundColor Red
    exit 1
}

# Install vex package
Write-Host "  Installing VexNet package..."
& "$VENV_DIR\Scripts\pip.exe" install --upgrade pip 2>&1 | Out-Null
& "$VENV_DIR\Scripts\pip.exe" install vexnet 2>&1 | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Host "  pip install failed. Trying from GitHub..."
    & "$VENV_DIR\Scripts\pip.exe" install "git+https://github.com/vexnet/vex.git" 2>&1 | Out-Null
}

# Create default config if none exists
$configDir = "$env:USERPROFILE\.vex"
$configFile = "$configDir\config.toml"
if (-not (Test-Path $configFile)) {
    New-Item -ItemType Directory -Force -Path $configDir | Out-Null
    @"
[llm]
provider = "ollama"
model = "glm4:latest"

[llm.ollama]
base_url = "http://localhost:11434/v1"

[security]
autonomy_level = 1
max_agent_depth = 3
max_tool_rounds = 25

[audit]
enabled = true
directory = ".vex/audit"
"@ | Set-Content -Path $configFile -Encoding utf8
    Write-Host "  Default config created at $configFile" -ForegroundColor Green
}

# ─── Step 5: Create shortcuts ───
Write-Host "[5/5] Creating shortcuts..." -ForegroundColor Yellow

# Create batch launcher in a PATH-accessible location
$launcherDir = "$env:USERPROFILE\.vex\bin"
New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null

# vex.cmd launcher
@"
@echo off
"%USERPROFILE%\.vex\venv\Scripts\vex.exe" %*
"@ | Set-Content -Path "$launcherDir\vex.cmd" -Encoding ascii

# Add to user PATH if not already there
$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$launcherDir*") {
    [System.Environment]::SetEnvironmentVariable("Path", "$userPath;$launcherDir", "User")
    $env:Path = "$env:Path;$launcherDir"
    Write-Host "  Added VexNet to PATH." -ForegroundColor Green
}

# ─── Done! ───
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "     VexNet installed successfully!     " -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Quick start:" -ForegroundColor Cyan
Write-Host "    vex                    Start the interactive agent" -ForegroundColor White
Write-Host "    vex --telegram         Start the Telegram bot" -ForegroundColor White
Write-Host ""
Write-Host "  Configuration:" -ForegroundColor Cyan
Write-Host "    Config file: $configFile" -ForegroundColor White
Write-Host ""
Write-Host "  Telegram setup:" -ForegroundColor Cyan
Write-Host "    1. Create a bot via @BotFather on Telegram" -ForegroundColor White
Write-Host "    2. Set TELEGRAM_BOT_TOKEN=your_token" -ForegroundColor White
Write-Host "    3. Run: vex --telegram" -ForegroundColor White
Write-Host ""
Write-Host "  You may need to restart your terminal for PATH changes." -ForegroundColor Yellow
Write-Host ""
