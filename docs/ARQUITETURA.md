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
├── sounds/                 # clipes salvos como som (ignorado pelo git)
├── docs/ARQUITETURA.md     # este documento
└── soundmod/
    ├── config.py           # carrega/salva config.json, caminhos
    ├── codec.py            # ffmpeg: decode() e encode_mp3()
    ├── engine.py           # mixer e streams de áudio
    ├── voice.py            # efeitos de voz em tempo real (pitch, robô, autotune...)
    ├── recorder.py         # loopback + buffer circular + salvar mp3
    ├── hotkeys.py          # registro de hotkeys globais e captura de tecla
    ├── i18n.py             # textos em cada idioma, t(chave), detecção do idioma do Windows
    ├── theme.py            # identidade visual: paleta, fontes, glifos, ícone, barra de título
    ├── widgets.py          # ScrollFrame, KeyButton, EffectGrid, StatusPill, Waveform
    ├── assets/             # icon.ico (janela e .exe), icon-256.png (README), logo-32/48/64.png (cabeçalho)
    └── gui.py              # interface (App, SlotRow)
```

## 3. Módulos

### 3.1 `config.py`
- `load()` mescla `DEFAULTS` com `config.json`; ignora arquivo ausente/corrompido.
- `save(cfg)` grava JSON UTF-8.
- Campos: `language` (`"pt"`, `"en"` ou `null` = idioma do Windows), `mic_device`, `output_device`, `monitor_device`, `loopback_device` (nomes de dispositivo), `mix_mic`, `monitor`, `master_volume`, `clip_seconds`, `voice_effect` (nome em `voice.EFFECTS`), `hear_self`, `clip_trim` (`[início, fim]` em s do trecho do clipe, ou `null` = inteiro), `save_clip_key`, `play_clip_key`, `stop_key`, `slots` (lista de `{key, path, volume}`).
- `slots[].path` pode ser relativo à pasta do programa (`sounds/x.mp3`, usado pelos clipes salvos); `resolve(path)` devolve o caminho absoluto. Assim a pasta pode ser copiada numa atualização sem quebrar os caminhos.
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
3. `OutputStream` opcional de monitor (fones) → `_mon_cb` consome `mon_buf`, alimentado pelo `_out_cb` com os sons e, só se `hear_self` estiver ligado, com a voz já processada.

**Voz:** `_pull_mic` tira um bloco de `mic_buf` e aplica `self.voice` (efeito de `voice.make`, ou `None`). `set_voice(nome)` troca o objeto inteiro, sem lock: o callback lê a referência uma vez por bloco. Se o efeito lançar exceção, ele é desligado para não derrubar o stream.

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
- `App(ctk.CTk)`: cabeçalho (logo, "Ao vivo", idioma, parar tudo), coluna principal com os cards **Sons** e **Clipe do áudio do PC**, painel lateral (`SIDEBAR` = 340 px) com **Dispositivos** e **Efeito de voz**, e barra de status. `_build` chama `_build_header`, `_build_sounds`, `_build_clip`, `_build_devices` e `_build_voice`.
- **`SlotRow`** (uma por slot, e é o id do canal no engine): um cartão (`frame`) com `KeyButton`, botão de arquivo, nome, tempo `m:ss / m:ss`, progresso (arrastar = `seek`), volume (0–1,5, ao vivo), ▶ ⏸ ■ e lixeira. A borda fica verde enquanto toca.
- **Card de voz:** `EffectGrid` 3×3 com os efeitos (devolve o nome interno, não o texto traduzido) e o switch "Ouvir minha voz".
- **Card do clipe:** "Salvar como som" no título; segundos + `KeyButton` de salvar (●), `KeyButton` do clipe (▶) com ⏸ ■; e a `Waveform` com o corte. O "Parar tudo" fica no cabeçalho.
- **`_tick`** (a cada 100 ms, thread da GUI): executa as tarefas da fila `ui_queue`, lê `engine.state` de cada canal e atualiza tempo, progresso, cursor da onda, a cor verde do que está tocando e o indicador "Ao vivo". Enquanto o usuário arrasta o progresso, a atualização daquele slider pausa por 0,4 s para não brigar com o mouse.

### 3.7 `widgets.py`
- `ScrollFrame`: Canvas + `CTkScrollbar` próprio. **Não usar `CTkScrollableFrame`**, que trava no Python 3.15.
- `KeyButton`: pílula (`ícone + TECLA`) que executa a ação, seguida dos ícones ✎ (capturar tecla) e ⌫ (remover; desativado quando não há tecla). `capturing()`, `set_key()`, `set_active()` (verde enquanto toca).
- `EffectGrid`: grade de pílulas com uma selecionada (laranja). `select(valor, notify)`.
- `StatusPill`: bolinha verde "Ao vivo" ou cinza "Parado", conforme `engine.running`.
- `Waveform` (`tk.Canvas`): reduz o áudio a ~2000 picos e desenha barras arredondadas a cada 5 px, normalizadas. O trecho selecionado fica em laranja, o resto em cinza. As alças brancas (início/fim) são arrastáveis e chamam `on_range(ini, fim)` ao soltar; clicar no meio chama `on_seek(t)`. O cursor é movido por `set_pos(t)` sem redesenhar a onda.
- **Cuidado:** nunca criar atributos ou métodos com nomes do tkinter em subclasses de widgets (`master`, `children`, `tk`, `_unbind`, etc.). Atribuir `master` já gerou loop infinito em `_root`, e um método `_unbind` no `App` já quebrou o `unbind_all`.
- **Threads nunca mexem no Tk.** Atualizações vindas de outras threads vão por `_post(fn)` para a fila `ui_queue`, que o `_tick` executa. Chamar `after()` de outra thread antes do `mainloop` lança `RuntimeError` no Python 3.15 e mata a thread em silêncio.
- A barra de status (`_set_status`) mostra sempre uma linha só: mensagens de várias linhas (erros do ffmpeg) esticariam a janela.
- `_start_all()` (botão "Aplicar / Reiniciar" e início automático): lê a UI → `cfg`, reinicia `Engine` e `Recorder`, registra hotkeys, salva config e pré-carrega os arquivos em threads.

### 3.7.1 `theme.py`
- **Paleta** (constantes): fundo `BG` carvão quente, cards `CARD`, linhas e botões neutros `ITEM`, destaque `ACCENT` laranja, `GREEN` para o que está tocando, `DANGER` para remover e parar tudo. Nenhuma cor fica escrita direto na interface.
- `apply_colors()` ajusta o tema padrão do customtkinter **antes** de criar a janela; `load_fonts(root)` escolhe Segoe UI Variable (Windows 11) ou Segoe UI, e Segoe Fluent Icons ou Segoe MDL2 Assets para os ícones.
- **Ícones** são glifos da fonte de ícones do Windows (`PLAY`, `PAUSE`, `STOP`, `EDIT`, `CLEAR`, `DELETE`, `FOLDER`...), usados com `icon_button()`. Nada de imagens: ficam nítidos em qualquer escala.
- `set_app_id()` faz a barra de tarefas usar o ícone do app ao rodar do código (senão aparece o do Python); `style_titlebar()` pinta a barra de título na cor do fundo no Windows 11.
- **Cuidado:** `CTkButton` tem largura padrão de 140 px. Botões em grade com `sticky="ew"` precisam de `width` pequeno, senão forçam o painel a crescer (isso já empurrou o painel lateral e escondeu os nomes dos sons).
- **Ícone do app:** `assets/icon.ico` (16 a 256 px) é usado pela janela (`iconbitmap`) e pelo `.exe` (`--icon` no `build.ps1`, que também leva a pasta `assets` com `--add-data`). Foi gerado com Pillow fora do projeto, para o Pillow não entrar no executável.

### 3.8 `i18n.py`
- `TEXTS[idioma][chave]` guarda todos os textos da interface e das mensagens; `t("chave", valor=...)` devolve o texto no idioma atual. O idioma é global ao módulo.
- `set_language(None)` usa `detect()`: português se o Windows estiver em português, senão inglês.
- **Adicionar um idioma:** incluir em `LANGUAGES` e em `TEXTS`, com as mesmas chaves e os mesmos campos `{...}`.
- **Novo texto na interface:** nunca escrever o texto direto no código; criar a chave em todos os idiomas.
- **Cuidado:** dentro de uma função que chama `t()`, não usar `t` como variável local (ex.: tempo), porque isso esconde a função.

### 3.9 `voice.py`
Cada efeito é um objeto chamável `efeito(bloco) -> bloco` (mono float32, qualquer tamanho) que guarda estado entre blocos. Roda dentro do callback de áudio, então usa só numpy vetorizado: nada de loop por amostra. Custo medido: < 0,3 ms por bloco de 10 ms.

| Efeito | Como funciona |
|---|---|
| `deep` / `high` | `PitchShifter` (0,75 / 1,45): linha de atraso lida por dois cursores em contrafase com janelas sin² que somam 1. Latência média de meia janela (~21 ms). |
| `ogre` | pitch 0,62 + saturação (`tanh`) + passa-baixa FIR de 2,2 kHz |
| `robot` | STFT (1024/256) com a fase zerada: voz monótona em SR/HOP ≈ 188 Hz mantendo as palavras |
| `autotune` | `detect_pitch` (autocorrelação via FFT em 2048 amostras) e `PitchShifter` puxando para o semitom mais próximo, com histerese de 0,6 semitom para não alternar entre duas notas |
| `echo` | atraso de 280 ms com realimentação 0,45 (vetorizável porque o atraso é maior que o bloco) |
| `radio` | passa-banda FIR 400–3000 Hz + saturação |
| `alien` | pitch 1,3 com vibrato de 5 Hz |

- **Novo efeito:** criar a classe (ou `Chain(...)` de passos existentes), registrar em `make()` e em `EFFECTS`, e adicionar `fx_<nome>` em todos os idiomas do `i18n`.
- A razão do `PitchShifter` pode mudar a cada bloco (`efeito(x, razao)`); ela é interpolada dentro do bloco para não estalar.

## 4. Fluxos principais

**Carregar slots:** ao iniciar/aplicar (e ao escolher arquivo), uma thread chama `engine.set_sound(row, path)`.

**Tocar/parar um slot (hotkey ou botão da tecla):** `_toggle_slot(row)` → `engine.toggle(row)`: a primeira vez toca, a segunda para. O ▶ separado usa `engine.play(row)` (sempre toca, recomeçando). Se o canal ainda não estiver carregado, carrega numa thread e toca em seguida. `_out_cb` mixa no próximo bloco.

**Pausar / parar / buscar:** ⏸ → `engine.pause(row)`, ■ → `engine.stop(row)`, arrastar o progresso → `engine.seek(row, s)`.

**Salvar clipe (F5):** hotkey → thread → `recorder.save(clips/last_clip.mp3)` → `_load_clip(reset_trim=True)` decodifica e cria o canal `"clip"` → na GUI, `_show_clip` desenha a onda e aplica o trecho inteiro. Ao abrir o app, um clipe existente é carregado com o `clip_trim` salvo.

**Adicionar sons (+ Adicionar som):** `askopenfilenames` → para cada arquivo, `_add_sound` usa o primeiro slot sem arquivo (mantendo a tecla dele) ou cria um slot novo, e carrega numa thread.

**Salvar clipe como som:** `_save_as_sound` pede o nome (`CTkInputDialog`; cancelar não faz nada), remove caracteres inválidos e, numa thread, grava o trecho `[start, end)` da onda em `sounds/<nome>.mp3` (com sufixo `(2)`, `(3)`... se já existir). Depois `_sound_saved` adiciona o som com caminho relativo.

**Efeito de voz:** clique no botão → `_on_voice` → `engine.set_voice(nome)` e salva `voice_effect`.

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

Verificado com VB-CABLE: sons e microfone chegando ao CABLE Output, F5 gerando o mp3, monitor nos fones, hotkeys globais com o app em segundo plano, troca de idioma ao vivo, efeitos de voz (frequência de saída, custo por bloco, silêncio, blocos irregulares) com sinal sintético.

**Ainda não verificado:**
1. Efeitos de voz com voz humana real, de ouvido (só foram testados com sinal sintético).
2. Detecção automática do idioma num Windows em inglês.

## 8. Roadmap sugerido

1. **Testes automatizados** (`tests/`): codec, mixer (`_out_cb` com buffers sintéticos), efeitos de voz (os testes de frequência feitos à mão), `config`, buffer circular do recorder com fonte falsa.
2. **Robustez de dispositivos:** reabrir streams se um dispositivo sumir/trocar; recarregar lista de dispositivos.
3. **Voz:** hotkeys para trocar de efeito, intensidade ajustável (ex.: quantos semitons no grave/agudo), escala musical no autotune.
4. **Qualidade:** medidor de nível do mic/saída, renomear sons salvos.
5. **UX:** bandeja do sistema (minimizar para a bandeja), iniciar com o Windows, perfis de slots, arrastar-e-soltar de arquivos.
6. **Áudio:** fade-out ao parar, modo "segurar para tocar", limitador no lugar do clip duro.
7. **Distribuição:** assinar o `.exe` para evitar o aviso do SmartScreen.

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
