# Gera dist\SoundMod\SoundMod.exe (pasta com o executavel + dependencias).
# Uso: .\build.ps1           (pasta)
#      .\build.ps1 -OneFile  (um unico .exe, abre mais devagar)
param([switch]$OneFile)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -q -r requirements-dev.txt

# o PyInstaller apaga dist\SoundMod: preserva config e clipes do usuario
$keep = Join-Path $env:TEMP "soundmod-keep"
Remove-Item $keep -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path dist\SoundMod) {
    New-Item -ItemType Directory $keep | Out-Null
    foreach ($f in "config.json", "clips") {
        if (Test-Path "dist\SoundMod\$f") { Copy-Item "dist\SoundMod\$f" $keep -Recurse }
    }
}

$mode = if ($OneFile) { "--onefile" } else { "--onedir" }
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed $mode `
    --name SoundMod `
    --collect-all customtkinter `
    --collect-all imageio_ffmpeg `
    --collect-all pyaudiowpatch `
    --collect-all sounddevice `
    main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou" }

if ((Test-Path $keep) -and -not $OneFile) {
    Copy-Item "$keep\*" dist\SoundMod -Recurse -Force
    Remove-Item $keep -Recurse -Force
}

$out = if ($OneFile) { "dist\SoundMod.exe" } else { "dist\SoundMod\SoundMod.exe" }
Write-Host "Pronto: $out"
