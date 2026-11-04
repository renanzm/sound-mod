# Gera dist\SoundMod\SoundMod.exe (pasta com o executavel + dependencias).
# Uso: .\build.ps1           (pasta)
#      .\build.ps1 -OneFile  (um unico .exe, abre mais devagar)
param([switch]$OneFile)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Get-Process SoundMod -ErrorAction SilentlyContinue) {
    throw "Feche o Sound Mod antes de compilar (os arquivos de dist\SoundMod estao em uso)."
}

if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -q -r requirements-dev.txt

# o PyInstaller apaga dist\SoundMod: preserva config e clipes do usuario.
# Se sobrou backup de um build que falhou, ele e o mais confiavel: reutiliza em vez de recriar.
$keep = Join-Path $env:TEMP "soundmod-keep"
if (-not (Test-Path $keep) -and (Test-Path dist\SoundMod)) {
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
