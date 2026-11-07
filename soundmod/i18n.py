"""Textos da interface em cada idioma. Para adicionar um idioma: inclua em LANGUAGES e TEXTS."""
import ctypes

LANGUAGES = {"pt": "Português", "en": "English"}

TEXTS = {
    "pt": {
        "none": "(nenhum)",
        "default_speaker": "(alto-falante padrão)",
        "mic": "Microfone real",
        "output": "Saída -> cabo virtual",
        "monitor": "Ouvir sons em (fones)",
        "loopback": "Capturar áudio do PC",
        "mix_mic": "Misturar meu microfone",
        "hear_sounds": "Ouvir os sons",
        "master_volume": "Volume geral",
        "apply": "Aplicar / Reiniciar",
        "no_cable": "Cabo virtual não encontrado. Instale o VB-CABLE (vb-audio.com/Cable), reinicie o app e "
                    "use 'CABLE Output' como microfone no Discord/jogo.",
        "sounds": "Sons",
        "sounds_hint": "▶ toca/para  ·  ✎ muda a tecla  ·  ⌫ remove a tecla  ·  um som por vez",
        "add_sound": "+ Adicionar som",
        "file": "Arquivo...",
        "no_file": "(sem arquivo)",
        "audio_files": "Áudio",
        "all_files": "Todos",
        "save_last": "Salvar últimos",
        "seconds": "seg",
        "clip": "Clipe",
        "stop_all": "Parar tudo",
        "clip_hint": "Arraste as alças laranjas para escolher o trecho que toca; clique na onda para mudar a posição.",
        "no_clip": "Nenhum clipe ainda: pressione a tecla de salvar",
        "selection": "trecho {sel:.1f}s de {total:.1f}s",
        "ready": "Pronto.",
        "loaded": "Carregado: {name}",
        "load_error": "Erro ao carregar {name}: {e}",
        "slot_empty": "Esse slot não tem arquivo.",
        "engine_stopped": "Engine parada: escolha a saída e clique em Aplicar.",
        "playing": "Tocando: {name}",
        "stopped": "Parado: {name}",
        "press_key": "tecla...",
        "key_removed": "Tecla removida.",
        "finish_key_first": "Pressione a nova tecla antes de trocar o idioma.",
        "clip_save_error": "Erro ao salvar clipe: {e}",
        "clip_saved": "Clipe salvo ({dur:.1f}s): {name}",
        "clip_open_error": "Erro ao abrir clipe: {e}",
        "no_clip_saved": "Ainda não há clipe salvo.",
        "clip_playing": "Tocando clipe",
        "clip_stopped": "Clipe parado",
        "warn_output": "AVISO: a saída deve ser o cabo virtual (CABLE Input)",
        "monitor_off": "monitor desligado: escolha seus fones em 'Ouvir sons em'",
        "audio_on": "áudio ligado",
        "audio_error": "áudio: {e}",
        "capture_on": "gravação do PC ligada",
        "capture_error": "gravação do PC: {e}",
        "invalid_key": "Tecla inválida: {keys}",
        "select_output": "Selecione o dispositivo de saída (cabo virtual).",
        "nothing_recorded": "Nada gravado ainda (sem áudio tocando no PC).",
        "decode_failed": "falha ao decodificar",
        "encode_failed": "falha ao gerar mp3",
    },
    "en": {
        "none": "(none)",
        "default_speaker": "(default speaker)",
        "mic": "Real microphone",
        "output": "Output -> virtual cable",
        "monitor": "Hear sounds on (headphones)",
        "loopback": "Capture PC audio",
        "mix_mic": "Mix my microphone",
        "hear_sounds": "Hear the sounds",
        "master_volume": "Master volume",
        "apply": "Apply / Restart",
        "no_cable": "Virtual cable not found. Install VB-CABLE (vb-audio.com/Cable), restart the app and "
                    "use 'CABLE Output' as the microphone in Discord/your game.",
        "sounds": "Sounds",
        "sounds_hint": "▶ play/stop  ·  ✎ change key  ·  ⌫ remove key  ·  one sound at a time",
        "add_sound": "+ Add sound",
        "file": "File...",
        "no_file": "(no file)",
        "audio_files": "Audio",
        "all_files": "All files",
        "save_last": "Save last",
        "seconds": "sec",
        "clip": "Clip",
        "stop_all": "Stop all",
        "clip_hint": "Drag the orange handles to choose the part that plays; click the waveform to change the position.",
        "no_clip": "No clip yet: press the save key",
        "selection": "selection {sel:.1f}s of {total:.1f}s",
        "ready": "Ready.",
        "loaded": "Loaded: {name}",
        "load_error": "Error loading {name}: {e}",
        "slot_empty": "This slot has no file.",
        "engine_stopped": "Audio engine stopped: choose the output and click Apply.",
        "playing": "Playing: {name}",
        "stopped": "Stopped: {name}",
        "press_key": "key...",
        "key_removed": "Key removed.",
        "finish_key_first": "Press the new key before changing the language.",
        "clip_save_error": "Error saving clip: {e}",
        "clip_saved": "Clip saved ({dur:.1f}s): {name}",
        "clip_open_error": "Error opening clip: {e}",
        "no_clip_saved": "No clip saved yet.",
        "clip_playing": "Playing clip",
        "clip_stopped": "Clip stopped",
        "warn_output": "WARNING: the output should be the virtual cable (CABLE Input)",
        "monitor_off": "monitor off: choose your headphones in 'Hear sounds on'",
        "audio_on": "audio on",
        "audio_error": "audio: {e}",
        "capture_on": "PC audio capture on",
        "capture_error": "PC audio capture: {e}",
        "invalid_key": "Invalid key: {keys}",
        "select_output": "Select the output device (virtual cable).",
        "nothing_recorded": "Nothing recorded yet (no audio playing on the PC).",
        "decode_failed": "failed to decode",
        "encode_failed": "failed to create mp3",
    },
}

_lang = "en"


def detect():
    """Portugues se o Windows estiver em portugues; senao ingles."""
    try:
        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
    except (AttributeError, OSError):
        return "en"
    return "pt" if primary == 0x16 else "en"


def set_language(lang):
    """lang None ou desconhecido usa o idioma do sistema."""
    global _lang
    _lang = lang if lang in LANGUAGES else detect()


def current():
    return _lang


def t(key, **values):
    return TEXTS[_lang][key].format(**values)
