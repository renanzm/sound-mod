# Sound Mod — Manual de Arquitetura e Desenvolvimento

Soundboard para Windows que toca sons no canal do microfone, com hotkeys globais e gravação dos últimos N segundos do áudio do PC.

## 1. Visão geral

### 1.1 Objetivo
- Tocar arquivos de áudio (mp3, wav, ogg, flac, m4a...) no "microfone" ao apertar uma tecla ou clicar num botão.
- Misturar o microfone real com os sons, para falar e tocar ao mesmo tempo.
- Gravar os últimos N segundos (padrão 5) do áudio do PC em mp3 (F5) e tocá-lo no microfone (F6).
- Interface gráfica para atribuir arquivo, tecla e volume a cada slot.

### 1.2 Como o áudio chega ao "microfone"
O Windows não permite injetar áudio num microfone físico. A solução padrão é um **cabo de áudio virtual** (VB-CABLE):

```
Microfone real ──┐
                 ├─► [Mixer do app] ─► CABLE Input ═► CABLE Output ─► Discord/jogo (microfone)
Sons (F1..F4) ───┘          │
                            └─► Fones (monitor, só para você ouvir)

Áudio do PC ─► WASAPI loopback ─► buffer circular (N s) ─► F5 grava mp3 ─► F6 toca como som
```

O app depende do VB-CABLE instalado. Sem ele a GUI avisa e o mixer não tem para onde enviar.

### 1.3 Stack

| Função | Biblioteca |
|---|---|
| I/O de áudio (mic, cabo, fones) | `sounddevice` (PortAudio, WASAPI) |
| Captura do áudio do PC | `PyAudioWPatch` (WASAPI loopback) |
| Decodificar/codificar mp3/wav/etc. | `imageio-ffmpeg` (binário ffmpeg embutido) |
| Hotkeys globais | `keyboard` |
| Interface | `customtkinter` |
| DSP/buffers | `numpy` |

Ambiente alvo: Windows 11, Python 3.15. Não há dependência que exija compilador C (`miniaudio` foi descartado por isso; `pydub` por depender de `audioop`, removido da stdlib).

## 2. Estrutura do repositório

```
sound-mod/
├── main.py                 # ponto de entrada: abre a GUI
├── requirements.txt
├── config.json             # gerado em runtime (ignorado pelo git)
├── clips/last_clip.mp3     # clipe do F5 (ignorado pelo git)
├── docs/ARQUITETURA.md     # este documento
└── soundmod/
    ├── config.py           # carrega/salva config.json, caminhos
    ├── codec.py            # ffmpeg: decode() e encode_mp3()
    ├── engine.py           # mixer e streams de áudio
    ├── recorder.py         # loopback + buffer circular + salvar mp3
    ├── hotkeys.py          # registro de hotkeys globais e captura de tecla
    ├── i18n.py             # textos em cada idioma, t(chave), detecção do idioma do Windows
    ├── widgets.py          # ScrollFrame, KeyButton (botão dividido), Waveform
    └── gui.py              # interface (App, SlotRow)
```

## 3. Módulos

### 3.1 `config.py`
- `load()` mescla `DEFAULTS` com `config.json`; ignora arquivo ausente/corrompido.
- `save(cfg)` grava JSON UTF-8.
- Campos: `language` (`"pt"`, `"en"` ou `null` = idioma do Windows), `mic_device`, `output_device`, `monitor_device`, `loopback_device` (nomes de dispositivo), `mix_mic`, `monitor`, `master_volume`, `clip_seconds`, `clip_trim` (`[início, fim]` em s do trecho do clipe, ou `null` = inteiro), `save_clip_key`, `play_clip_key`, `stop_key`, `slots` (lista de `{key, path, volume}`).
- Dispositivos são guardados **por nome** (índices mudam entre sessões). `null` = escolher automaticamente, `""` = nenhum. O texto antigo `"(nenhum)"` de configs anteriores ainda é aceito.

### 3.2 `codec.py`
- Formato interno único: **float32, estéreo, 48 kHz**, shape `(N, 2)`.
- `decode(path)`: roda `ffmpeg -f f32le -ac 2 -ar 48000` e lê o stdout. Qualquer formato que o ffmpeg abra funciona.
- `encode_mp3(pcm_int16, rate, channels, out)`: envia PCM por stdin ao ffmpeg (`libmp3lame -q:a 2`).
- Usa `CREATE_NO_WINDOW` para não abrir console.

### 3.3 `engine.py`
Classe `Engine`, no coração do app.

**Streams** (todos a 48 kHz, bloco de 480 frames = 10 ms, WASAPI com `auto_convert=True`):
1. `InputStream` do microfone (mono) → `_mic_cb` empilha em `mic_buf`.
2. `OutputStream` para o cabo virtual → `_out_cb` mixa sons + mic e escreve a saída.
3. `OutputStream` opcional de monitor (fones) → `_mon_cb` consome `mon_buf`, alimentado pelo `_out_cb` apenas com os sons (sem o mic, para você não se ouvir).

Os streams abrem com `open(mic, saida, monitor)` e fecham com `close()`.

**Canais:** cada som é um `_Channel(data, pos, start, end, gain, playing)` guardado em `channels[cid]`. O `cid` é o objeto `SlotRow` de cada slot, ou a string `"clip"`. Só o trecho `[start, end)` toca: o slot usa o arquivo inteiro e o clipe usa o corte da forma de onda. Tudo é protegido por `lock`.

| Método | Efeito |
|---|---|
| `set_sound(cid, path, gain)` | decodifica (com cache) e cria o canal parado; retorna a duração |
| `play(cid)` | se já toca, recomeça do início do trecho; senão continua de `pos` (para os outros canais) |
| `toggle(cid)` | tocando → para; senão toca como `play`. Retorna o novo estado, ou `None` se o canal não existe |
| `pause(cid)` | alterna pausa/continuar (parado no início: nada); continuar também para os outros canais |
| `stop(cid)` / `stop_all()` | para e volta `pos` ao início do trecho |
| `seek(cid, s)` | move `pos`, limitado ao trecho |
| `rekey(antigo, novo)` | passa o canal para outro id sem interromper o som (usado ao recriar a janela) |
| `set_gain`, `set_range(cid, ini, fim)` | volume ao vivo, corte do trecho |
| `state(cid)` | `(pos_s, duração_total_s, tocando)` para a GUI |

`_render_sounds` soma o próximo bloco de cada canal tocando e aplica o volume geral. Ao chegar ao fim do trecho, o canal para e volta ao início. **Só um som por vez:** `play`, `toggle` e continuar uma pausa chamam `_solo(cid)`, que para todos os outros canais (inclusive o clipe) e os volta ao início.

**Latência:** `mic_buf` e `mon_buf` descartam o excedente acima de 250 ms (`MAX_LAG`) para a defasagem não crescer se os relógios dos dispositivos divergirem.

**Cache:** `load()` guarda o PCM decodificado por caminho; `invalidate(path)` limpa (usado após regravar o clipe).

**Saída:** soma, `np.clip` em [-1, 1].

**Regras:** callbacks de áudio não alocam em excesso, não fazem I/O e não chamam a GUI. `set_sound` pode demorar e lançar exceção (decodificação), então roda em thread; os demais métodos de canal são instantâneos e podem ser chamados de qualquer thread.

### 3.4 `recorder.py`
Classe `LoopbackRecorder`.
- Abre o dispositivo loopback (padrão: alto-falante padrão; ou o escolhido por nome) em int16, na taxa e canais nativos.
- Uma thread lê por **polling** (`get_read_available`, 10 ms) e empilha chunks num `deque` que mantém no máximo `seconds * rate` frames.
- Sem `stream_callback`: o callback C do PyAudioWPatch travou no Python 3.15.
- `save(path)` concatena, corta os últimos N s e codifica em mp3. Retorna a duração.
- Observação do WASAPI loopback: sem áudio tocando no PC não chegam amostras, então o buffer pode estar vazio ("Nada gravado ainda").
- Se o monitor e o loopback usam o mesmo dispositivo (ex.: os fones), o clipe também grava os sons do próprio app. Não há realimentação no microfone, porque o loopback nunca captura o cabo.

### 3.5 `hotkeys.py`
- `HotkeyManager.register([(tecla, callback), ...])` usa `keyboard.add_hotkey`; teclas vazias são ignoradas, teclas inválidas voltam como lista de erros. `clear()` remove tudo.
- `capture_key()` bloqueia até o usuário pressionar uma tecla/combinação (`keyboard.read_hotkey`); deve rodar em thread.
- Callbacks chegam na thread do `keyboard`, nunca na da GUI.

### 3.6 `gui.py`
- `App(ctk.CTk)`: seções de dispositivos, lista de slots, área do clipe e barra de status.
- **`SlotRow`** (uma por slot, e é o id do canal no engine): `KeyButton` (▶ toca / ✎ muda a tecla), "Arquivo...", nome, tempo `m:ss / m:ss`, slider de progresso (arrastar = `seek`), slider de volume (0–1,5, ao vivo), ▶ ⏸ ■ e ✕.
- **Área do clipe:** segundos + `KeyButton` de salvar (●), `KeyButton` do clipe (▶) com ⏸ ■, `KeyButton` de parar tudo e a `Waveform` com o corte.
- **`_tick`** (a cada 100 ms, thread da GUI): lê `engine.state` de cada canal e atualiza tempo, progresso, cursor da onda e a cor verde do botão que está tocando. Enquanto o usuário arrasta o progresso, a atualização daquele slider pausa por 0,4 s para não brigar com o mouse.

### 3.7 `widgets.py`
- `ScrollFrame`: Canvas + `CTkScrollbar` próprio. **Não usar `CTkScrollableFrame`**, que trava no Python 3.15.
- `KeyButton`: três botões lado a lado. O principal (`ícone + TECLA`) executa a ação; o ✎ chama a captura de tecla; o ⌫ remove a tecla (fica desativado quando não há tecla). `capturing()`, `set_key()`, `set_active()`.
- `Waveform` (`tk.Canvas`): reduz o áudio a ~2000 picos e desenha uma coluna por pixel, normalizada. O trecho selecionado fica em azul, o resto em cinza. As alças laranjas (início/fim) são arrastáveis e chamam `on_range(ini, fim)` ao soltar; clicar no meio chama `on_seek(t)`. O cursor branco é movido por `set_pos(t)` sem redesenhar a onda.
- **Cuidado:** nunca criar atributos ou métodos com nomes do tkinter em subclasses de widgets (`master`, `children`, `tk`, `_unbind`, etc.). Atribuir `master` já gerou loop infinito em `_root`, e um método `_unbind` no `App` já quebrou o `unbind_all`.
- Toda atualização de widget vinda de outra thread passa por `self.after(0, ...)` (`_say`).
- `_start_all()` (botão "Aplicar / Reiniciar" e início automático): lê a UI → `cfg`, reinicia `Engine` e `Recorder`, registra hotkeys, salva config e pré-carrega os arquivos em threads.

### 3.8 `i18n.py`
- `TEXTS[idioma][chave]` guarda todos os textos da interface e das mensagens; `t("chave", valor=...)` devolve o texto no idioma atual. O idioma é global ao módulo.
- `set_language(None)` usa `detect()`: português se o Windows estiver em português, senão inglês.
- **Adicionar um idioma:** incluir em `LANGUAGES` e em `TEXTS`, com as mesmas chaves e os mesmos campos `{...}`.
- **Novo texto na interface:** nunca escrever o texto direto no código; criar a chave em todos os idiomas.
- **Cuidado:** dentro de uma função que chama `t()`, não usar `t` como variável local (ex.: tempo), porque isso esconde a função.

## 4. Fluxos principais

**Carregar slots:** ao iniciar/aplicar (e ao escolher arquivo), uma thread chama `engine.set_sound(row, path)`.

**Tocar/parar um slot (hotkey ou botão da tecla):** `_toggle_slot(row)` → `engine.toggle(row)`: a primeira vez toca, a segunda para. O ▶ separado usa `engine.play(row)` (sempre toca, recomeçando). Se o canal ainda não estiver carregado, carrega numa thread e toca em seguida. `_out_cb` mixa no próximo bloco.

**Pausar / parar / buscar:** ⏸ → `engine.pause(row)`, ■ → `engine.stop(row)`, arrastar o progresso → `engine.seek(row, s)`.

**Salvar clipe (F5):** hotkey → thread → `recorder.save(clips/last_clip.mp3)` → `_load_clip(reset_trim=True)` decodifica e cria o canal `"clip"` → na GUI, `_show_clip` desenha a onda e aplica o trecho inteiro. Ao abrir o app, um clipe existente é carregado com o `clip_trim` salvo.

**Cortar o clipe:** soltar uma alça → `_clip_range` → `engine.set_range("clip", ini, fim)` e salva `clip_trim`.

**Tocar/parar clipe (F6):** `_toggle_clip` → `engine.toggle("clip")`, só no trecho escolhido.

**Parar tudo (F12):** `engine.stop_all()`.

**Trocar idioma:** menu → `_on_language` → `_change_language`: `_read_ui` guarda o que está na janela, os widgets são destruídos e `_build` recria tudo no novo idioma. `engine.rekey` passa cada canal para a nova `SlotRow`, então o som não para. Bloqueado enquanto uma tecla está sendo capturada.

**Trocar tecla:** `_rebind` limpa as hotkeys → `capture_key` em thread → `_rebound` grava no `cfg`, registra de novo e salva o `config.json`.

**Remover tecla (⌫):** `_clear_key` → `_set_key(..., "")`: a ação fica sem hotkey, mas o botão continua funcionando com o mouse.

## 5. Threads

| Thread | O que faz | Regra |
|---|---|---|
| Principal (Tk) | GUI | só ela mexe em widgets |
| Callbacks PortAudio | mic, saída, monitor | rápidos, sem I/O/GUI |
| Leitura do loopback | polling → buffer | trava só no `lock` do buffer |
| `keyboard` | dispara callbacks de hotkey | só delega a threads de trabalho |
| Workers curtos | decodificar, salvar mp3, capturar tecla | reportam via `self.after` |

## 6. Decisões e restrições

- **Taxa fixa de 48 kHz estéreo** internamente; o WASAPI converte (`auto_convert`) para o que cada dispositivo aceitar.
- **Nomes de dispositivo** na config, resolvidos para índices a cada inicialização.
- **Só WASAPI** na listagem de dispositivos, para evitar entradas duplicadas (MME/DirectSound/WDM-KS).
- **ffmpeg embutido** evita exigir instalação do usuário.
- **Windows Audio (Audiosrv)** precisa estar rodando; se estiver parado, nenhum dispositivo aparece (já ocorreu durante o desenvolvimento).
- Hotkeys globais com `keyboard` podem exigir executar como administrador para capturar teclas em jogos que rodam elevados.

## 7. Estado atual e pendências

Verificado: codec (mp3 ida e volta), mixer offline (volume, parada), abertura da GUI.

**Ainda não verificado** (bloqueado pelo serviço de áudio parado e pela falta do VB-CABLE):
1. Streams reais: mic + sons → CABLE Input, ouvidos pelo CABLE Output.
2. Loopback por polling (versão nova do `recorder.py`) e geração do mp3 do F5.
3. Monitor nos fones sem eco do microfone.
4. Hotkeys globais com o app em segundo plano.

## 8. Roadmap sugerido

1. **Validação de ponta a ponta** (itens da seção 7) com VB-CABLE instalado.
2. **Testes automatizados** (`tests/`): codec, mixer (`_out_cb` com buffers sintéticos), `config`, buffer circular do recorder com fonte falsa.
3. **Robustez de dispositivos:** reabrir streams se um dispositivo sumir/trocar; recarregar lista de dispositivos.
4. **Qualidade:** medidor de nível do mic/saída, botão "tocar clipe" na GUI, escolha do nome/pasta do clipe, vários clipes (histórico com timestamp).
5. **UX:** bandeja do sistema (minimizar para a bandeja), iniciar com o Windows, perfis de slots, arrastar-e-soltar de arquivos.
6. **Áudio:** fade-out ao parar, modo "segurar para tocar", limitador no lugar do clip duro, reamostragem própria se o `auto_convert` causar artefatos.
7. **Distribuição:** empacotar com PyInstaller em `.exe` (incluir o binário do ffmpeg do `imageio-ffmpeg`).

## 9. Como rodar e depurar

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

Dicas:
- Teste scripts que podem travar com `faulthandler.dump_traceback_later(15, exit=True)` e `python -u`.
- Para listar dispositivos: `sounddevice.query_devices()` e `PyAudio().get_loopback_device_info_generator()`.
- Convenções: comentários em português; textos da interface sempre via `i18n.t()`; cada módulo com uma responsabilidade; sem acesso à GUI fora da thread principal.
