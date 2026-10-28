# Sound Mod

Soundboard para Windows que toca sons no seu microfone (via cabo de audio virtual), com hotkeys globais
e gravacao dos ultimos segundos do audio do PC.

## Requisitos
- Windows 10/11, Python 3.11+
- [VB-CABLE](https://vb-audio.com/Cable/) (gratis). Depois de instalar, reinicie o app.

## Instalar e rodar
```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Como usar
1. **Microfone real**: seu mic fisico. **Saida -> cabo virtual**: `CABLE Input`.
2. No Discord/jogo, escolha **CABLE Output** como microfone.
3. Atribua arquivos (mp3, wav, ogg, flac...) e teclas aos slots (clique no botao da tecla e pressione a nova).
4. **F5** salva os ultimos N segundos do audio do PC em `clips/last_clip.mp3`; **F6** toca o clipe. **F12** para tudo.

O audio e codificado/decodificado com um ffmpeg embutido (pacote `imageio-ffmpeg`), sem instalar nada a mais.
Configuracoes ficam em `config.json`.

## Gerar executável (.exe)
```
powershell -ExecutionPolicy Bypass -File build.ps1
```
Gera `dist\SoundMod\SoundMod.exe` (pasta completa, inicia rápido; distribua a pasta inteira).
Use `build.ps1 -OneFile` para um único `.exe` (abre mais devagar). O ffmpeg vai embutido.
`config.json` e `clips\` são criados ao lado do `.exe`. O VB-CABLE continua sendo necessário.
