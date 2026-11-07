# Sound Mod

**English** | [Português](README.pt-BR.md)

**A Windows soundboard that plays sounds straight into your microphone.** Press a key (or click a button) and the sound goes out on your mic channel, for Discord, games, calls and streams, while you keep talking normally.

It can also record the **last few seconds of your PC audio** (5 s by default) so you can trim it and play it back on your mic.

## Features

- **Global hotkeys**: F1, F2, F3... play different sounds, even with the app in the background. Press once to play, press again to stop. Keys can be changed or removed.
- **Mic + sounds together**: mixes your real microphone with the sounds, with no device switching.
- **Any format**: mp3, wav, ogg, flac, m4a, aac... (ffmpeg is bundled, nothing else to install).
- **Per-sound controls**: ▶ play, ⏸ pause/resume, ■ stop, draggable progress bar (seek forward/back) and individual live volume.
- **One sound at a time**: playing a sound interrupts the current one.
- **PC audio clip**: one key saves the last N seconds to `clips/last_clip.mp3`, another plays it. The waveform lets you **choose the part** that plays.
- **Headphone monitor**: you hear the sounds while they go out on your mic.
- **English and Portuguese**: follows your Windows language, and you can switch at any time in the app.
- Lightweight dark interface (customtkinter).

## How it works

Windows doesn't allow injecting audio into a physical microphone, so the app uses a **virtual audio cable** (VB-CABLE):

```
Real microphone ──┐
                  ├─► Sound Mod ─► CABLE Input ═► CABLE Output ─► Discord/game (as microphone)
Sounds (F1, F2...)┘      └─► your headphones (monitor)
```

## Installation

### Option 1: executable (recommended)
1. Install [VB-CABLE](https://vb-audio.com/Cable/) (free) and restart your PC.
2. Download `SoundMod-vX.Y.Z-windows.zip` from the [latest release](../../releases/latest), extract the whole folder and open `SoundMod.exe`.

### Option 2: run from source
Requires Windows 10/11 and Python 3.11+.
```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## How to use

1. **Real microphone**: your physical mic. **Output -> virtual cable**: `CABLE Input`. **Hear sounds on**: your headphones (don't choose the cable here).
2. In Discord or your game, choose **CABLE Output** as the microphone. In Discord, turn off Noise Suppression, Echo Cancellation and Automatic Gain Control, which tend to cut sound effects.
3. Assign files to the slots. Each key button is split: **▶ F1** plays and, pressed again, stops; **✎** changes the key; **⌫** removes the key.
   Only one sound plays at a time: playing another interrupts the current one.
4. **F5** saves the last N seconds of PC audio and shows the waveform; drag the orange handles to choose the part. **F6** plays that part. **F12** stops everything.

To change the language, use the menu next to **Apply / Restart**. Settings are stored in `config.json` next to the program.

## Building the executable

```
powershell -ExecutionPolicy Bypass -File build.ps1
```
Creates `dist\SoundMod\SoundMod.exe` (use `-OneFile` for a single `.exe`). Close the app before building. `config.json` and the `clips\` folder are kept when you rebuild.

## Documentation

Architecture and development guide (in Portuguese): [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

## Known limitations

- Windows only (uses WASAPI and Windows global hotkeys).
- Requires VB-CABLE (or another virtual cable) to be installed.
- To capture keys in games running as administrator, run Sound Mod as administrator.

## License

[MIT](LICENSE)
