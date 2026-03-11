# VexNet Uninstaller for Windows
# Run: irm https://vexnet.ai/uninstall.ps1 | iex

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   VexNet Uninstaller for Windows       " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$VEX_DIR = "$env:USERPROFILE\.vex"

# ─── Confirm ───
Write-Host "This will remove VexNet and all its data from your system." -ForegroundColor Yellow
Write-Host ""
Write-Host "  The following will be deleted:"
Write-Host "    $VEX_DIR              (venv, config, data, chat history)"
Write-Host "    PATH entry"
Write-Host ""
Write-Host "  Note: Ollama and its models will NOT be removed." -ForegroundColor Yellow
Write-Host ""

$confirm = Read-Host "  Continue? [y/N]"
if ($confirm -notmatch "^[Yy]$") {
    Write-Host ""
    Write-Host "  Cancelled."
    Write-Host ""
    exit 0
}

Write-Host ""

# ─── Step 1: Remove VexNet directory ───
Write-Host "[1/2] Removing VexNet..." -ForegroundColor Yellow

if (Test-Path $VEX_DIR) {
    Remove-Item -Recurse -Force $VEX_DIR
    Write-Host "  Removed $VEX_DIR" -ForegroundColor Green
} else {
    Write-Host "  $VEX_DIR not found, skipping."
}

# ─── Step 2: Clean up PATH ───
Write-Host "[2/2] Cleaning up PATH..." -ForegroundColor Yellow

$launcherDir = "$env:USERPROFILE\.vex\bin"
$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")

if ($userPath -like "*$launcherDir*") {
    $newPath = ($userPath -split ";" | Where-Object { $_ -notlike "*\.vex\bin*" }) -join ";"
    [System.Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    $env:Path = ($env:Path -split ";" | Where-Object { $_ -notlike "*\.vex\bin*" }) -join ";"
    Write-Host "  Removed from PATH." -ForegroundColor Green
} else {
    Write-Host "  PATH already clean."
}

# ─── Done ───
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "   VexNet uninstalled successfully.     " -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  To also remove Ollama and its models:" -ForegroundColor White
Write-Host "    ollama rm qwen3:30b-a3b" -ForegroundColor White
Write-Host "    ollama rm nomic-embed-text:latest" -ForegroundColor White
Write-Host "    Then uninstall Ollama from Settings > Apps" -ForegroundColor White
Write-Host ""
Write-Host "  You may need to restart your terminal for PATH changes." -ForegroundColor Yellow
Write-Host ""
