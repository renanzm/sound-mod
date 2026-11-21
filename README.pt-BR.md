> [!IMPORTANT]
> **Este projeto foi migrado para Rust: [renanzm/sound-mod-rs](https://github.com/renanzm/sound-mod-rs).**
> Esta versão em Python não é mais mantida. A nova versão tem todas as funções daqui, mais ordem dos sons, coleções e uma nova interface neon, num único `.exe` sem nada para instalar. Ela lê o mesmo `config.json`: coloque o novo `SoundMod.exe` na pasta desta versão (ou copie o `config.json` e a pasta `sounds\` para o lado dele) e seus sons, teclas e dispositivos são importados na primeira abertura.

<img src="soundmod/assets/icon-256.png" width="96" alt="Sound Mod">

# Sound Mod

[English](README.md) | **Português**

**Soundboard para Windows que toca sons direto no seu microfone.** Aperte uma tecla (ou clique num botão) e o som sai no canal do microfone, para Discord, jogos, chamadas e streams, enquanto você continua falando normalmente.

Também grava os **últimos segundos do áudio do PC** (padrão 5 s) para você cortar e reproduzir no microfone.

## Recursos

- **Hotkeys globais**: F1, F2, F3... tocam sons diferentes, mesmo com o app em segundo plano. Aperte uma vez para tocar e de novo para parar. As teclas podem ser trocadas ou removidas.
- **Mic + sons juntos**: mistura seu microfone real com os sons, sem trocar de dispositivo.
- **Qualquer formato**: mp3, wav, ogg, flac, m4a, aac... (ffmpeg embutido, nada extra para instalar).
- **Controle por som**: ▶ tocar, ⏸ pausar/continuar, ■ parar, barra de progresso arrastável (avançar/voltar) e volume individual ao vivo.
- **Um som por vez**: tocar um som interrompe o atual.
- **Vários arquivos de uma vez**: o **+ Adicionar som** aceita vários arquivos; eles ocupam primeiro os slots vazios.
- **Efeitos de voz**: Grave, Agudo, Robô, Ogro, Autotune, Eco, Rádio e Alien, aplicados ao vivo no seu microfone. Ligue **Ouvir minha voz** para escutar como você está saindo.
- **Clipe do áudio do PC**: uma tecla salva os últimos N segundos em `clips/last_clip.mp3`; outra toca. A forma de onda permite **escolher o trecho** que será reproduzido, e **Salvar como som** guarda esse trecho como um som novo na lista (na pasta `sounds/`).
- **Monitor nos fones**: você ouve os sons enquanto eles saem no microfone.
- **Português e inglês**: segue o idioma do Windows, e você pode trocar quando quiser no app.
- Interface gráfica escura e leve (customtkinter).

## Como funciona

O Windows não permite injetar áudio num microfone físico, então o app usa um **cabo de áudio virtual** (VB-CABLE):

```
Microfone real ──┐
                 ├─► Sound Mod ─► CABLE Input ═► CABLE Output ─► Discord/jogo (como microfone)
Sons (F1, F2...) ┘      └─► seus fones (monitor)
```

## Instalação

### Opção 1: executável (recomendado)
1. Instale o [VB-CABLE](https://vb-audio.com/Cable/) (gratuito) e reinicie o PC.
2. Baixe o `SoundMod-vX.Y.Z-windows.zip` da [última release](../../releases/latest), extraia a pasta inteira e abra `SoundMod.exe`.

### Opção 2: rodar do código
Requer Windows 10/11 e Python 3.11+.
```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Como usar

1. **Microfone real**: seu microfone físico. **Saída → cabo virtual**: `CABLE Input`. **Ouvir sons em**: seus fones (não escolha o cabo aqui).
2. No Discord/jogo, escolha **CABLE Output** como microfone. No Discord, desligue supressão de ruído, cancelamento de eco e controle automático de ganho, que costumam cortar efeitos sonoros.
3. Atribua arquivos aos slots. Cada botão de tecla é dividido: **▶ F1** toca e, apertado de novo, para; **✎** muda a tecla; **⌫** remove a tecla.
   Só um som toca por vez: tocar outro interrompe o atual. O **+ Adicionar som** permite escolher vários arquivos de uma vez.
4. **F5** salva os últimos N segundos do áudio do PC e mostra a forma de onda; arraste as alças laranjas para escolher o trecho. **F6** toca o trecho. **F12** para tudo. **Salvar como som** pede um nome e adiciona o trecho escolhido aos seus sons.
5. **Efeito de voz**: escolha um efeito na barra abaixo dos dispositivos. Ele muda seu microfone ao vivo; **Normal** desliga. Marque **Ouvir minha voz** para se escutar nos fones.

Para trocar o idioma, use o menu ao lado de **Aplicar / Reiniciar**. As configurações ficam em `config.json` ao lado do programa, e os clipes salvos na pasta `sounds`. Ao atualizar, copie `config.json`, `clips` e `sounds` para a pasta nova.

## Gerar o executável

```
powershell -ExecutionPolicy Bypass -File build.ps1
```
Gera `dist\SoundMod\SoundMod.exe` (use `-OneFile` para um único `.exe`). Feche o app antes de compilar. O `config.json` e as pastas `clips\` e `sounds\` são preservados ao recompilar.

## Documentação

Arquitetura e guia de desenvolvimento: [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

## Limitações conhecidas

- Somente Windows (usa WASAPI e hotkeys globais do Windows).
- Depende do VB-CABLE (ou outro cabo virtual) instalado.
- Para capturar teclas em jogos que rodam como administrador, execute o Sound Mod como administrador.

## Licença

[MIT](LICENSE)
