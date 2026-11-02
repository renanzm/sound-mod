# Sound Mod

**Soundboard para Windows que toca sons direto no seu microfone.** Aperte uma tecla (ou clique num botão) e o som sai no canal do microfone, para Discord, jogos, chamadas e streams, enquanto você continua falando normalmente.

Também grava os **últimos segundos do áudio do PC** (padrão 5 s) para você cortar e reproduzir no microfone.

## Recursos

- **Hotkeys globais**: F1, F2, F3... tocam sons diferentes, mesmo com o app em segundo plano. As teclas são configuráveis.
- **Mic + sons juntos**: mistura seu microfone real com os sons, sem trocar de dispositivo.
- **Qualquer formato**: mp3, wav, ogg, flac, m4a, aac... (ffmpeg embutido, nada extra para instalar).
- **Controle por som**: ▶ tocar, ⏸ pausar/continuar, ■ parar, barra de progresso arrastável (avançar/voltar) e volume individual ao vivo.
- **Clipe do áudio do PC**: uma tecla salva os últimos N segundos em `clips/last_clip.mp3`; outra toca. A forma de onda permite **escolher o trecho** que será reproduzido.
- **Monitor nos fones**: você ouve os sons enquanto eles saem no microfone.
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
2. Baixe o `SoundMod-v1.0.0-windows.zip` na [página de Releases](../../releases), extraia e abra `SoundMod.exe`.

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
3. Atribua arquivos aos slots. Cada botão de tecla é dividido: **▶ F1** toca, **✎** muda a tecla.
4. **F5** salva os últimos N segundos do áudio do PC e mostra a forma de onda; arraste as alças laranjas para escolher o trecho. **F6** toca o trecho. **F12** para tudo.

As configurações ficam em `config.json` ao lado do programa.

## Gerar o executável

```
powershell -ExecutionPolicy Bypass -File build.ps1
```
Gera `dist\SoundMod\SoundMod.exe` (use `-OneFile` para um único `.exe`). O `config.json` e a pasta `clips\` são preservados ao recompilar.

## Documentação

Arquitetura e guia de desenvolvimento: [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

## Limitações conhecidas

- Somente Windows (usa WASAPI e hotkeys globais do Windows).
- Depende do VB-CABLE (ou outro cabo virtual) instalado.
- Para capturar teclas em jogos que rodam como administrador, execute o Sound Mod como administrador.

## Licença

[MIT](LICENSE)
