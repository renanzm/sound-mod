# Gera dist\SoundMod\SoundMod.exe (pasta com o executavel + dependencias).
# Uso: .\build.ps1           (pasta)
#      .\build.ps1 -OneFile  (um unico .exe, abre mais devagar)
param([switch]$OneFile)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -q -r requirements-dev.txt

$mode = if ($OneFile) { "--onefile" } else { "--onedir" }
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed $mode `
    --name SoundMod `
    --collect-all customtkinter `
    --collect-all imageio_ffmpeg `
    --collect-all pyaudiowpatch `
    --collect-all sounddevice `
    main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou" }

$out = if ($OneFile) { "dist\SoundMod.exe" } else { "dist\SoundMod\SoundMod.exe" }
Write-Host "Pronto: $out"
