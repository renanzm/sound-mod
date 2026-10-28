"""Hotkeys globais (funcionam com o app em segundo plano)."""
import keyboard


class HotkeyManager:
    def __init__(self):
        self._handles = []

    def clear(self):
        for h in self._handles:
            try:
                keyboard.remove_hotkey(h)
            except (KeyError, ValueError):
                pass
        self._handles = []

    def register(self, mapping):
        """mapping: lista de (tecla, callback). Teclas vazias sao ignoradas."""
        self.clear()
        errors = []
        for key, cb in mapping:
            if not key:
                continue
            try:
                self._handles.append(keyboard.add_hotkey(key, cb))
            except Exception as e:  # tecla invalida
                errors.append(f"{key}: {e}")
        return errors


def capture_key():
    """Bloqueia ate o usuario pressionar uma tecla/combinacao; retorna ex. 'f1' ou 'ctrl+shift+a'."""
    return keyboard.read_hotkey(suppress=False)
