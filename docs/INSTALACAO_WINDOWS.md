# Instalação e operação segura no Windows

## Pré-requisitos

- Windows 10/11, Python 3.11 ou mais recente com Tkinter disponível.
- FFmpeg e FFprobe no PATH. Confira no CMD: `ffmpeg -version` e `ffprobe -version`.
- Pillow e yt-dlp (`INSTALAR_WINDOWS.bat`). O yt-dlp pode precisar ser atualizado quando o YouTube alterar os formatos; falhas de acesso não são contornadas automaticamente.
- Espaço livre suficiente para prévias e finais: vídeo 1080×1920 pode consumir centenas de MB.

Para instalar o FFmpeg via winget quando disponível: `winget install --id Gyan.FFmpeg -e`. Feche/reabra o terminal após instalar para atualizar o PATH. Não use a opção de associar mídia diferente da fonte analisada: mesmo vídeo reencodificado tem outro hash e precisa ser reanalisado/retificado na origem.

## Operação

1. Extraia todo o ZIP deste programa em uma pasta sem `.venv` compartilhada com projetos antigos.
2. Execute `INSTALAR_WINDOWS.bat` e depois `INICIAR_WINDOWS.bat`.
3. Após importar o exemplo, cole a URL do YouTube no campo novo e clique **BAIXAR VÍDEO DO YOUTUBE** (somente vídeos de uso autorizado), ou use **VINCULAR MP4 ORIGINAL**.
4. O download fica em `downloads/attempts/<id>`. Se o SHA256 for diferente, clique **USAR DOWNLOAD NAS PRÉVIAS (REVISÃO)**. A verificação exige o mesmo ID e duração (±3 s), streams, hash real e confirmação explícita. **Não é prova de sincronização** e a fonte do Analyzer não é modificada. Gere PRÉVIAS e confira cada fala/câmera antes de aprovar; se os tempos divergirem, reanalise esse MP4.
5. Revise Reels/Stories e execute as prévias individualmente ou em lote.
6. Abra a prévia gerada, assista e confira contexto, narração, começo/fim, enquadramento, legenda e autorização dos direitos.
7. Marque os dois campos de revisão e aprove aquela prévia. Só então renderize o final.

## Segurança e qualidade

- **ZIP**: manifesto SHA256, tipos e caminhos permitidos, controle anti-zip-slip e tamanho limitado. A fonte nunca é extraída de forma arbitrária.
- **Mídia**: SHA256 deve coincidir com o `source_sha256` do plano. O download acontece só após comando explícito, e não baixa durante o render; cópia recodificada/qualidade diferente pode ser rejeitada.
- **Legendas**: ASS/SRT do R57 são *rascunhos*; a revisão humana é obrigatória antes de embutir no vídeo. Um corte Reel cuja janela mudou exige novo alinhamento.
- **Câmera**: fonte 16:9 é preservada integralmente com fundo desfocado por padrão; crop manual requer inspeção humana.
- **Stories**: a ordem original é intocável em V1.0, evitando gaps artificiais, embora o início/fim por minuto possa precisar de revisão editorial futura.
- **Saídas**: cada execução usa uma pasta isolada; falhas preservam logs. O render final é bloqueado sem aprovação da prévia atual.
- **Direitos**: aprovação do preview não comprova direitos; nenhum upload automático ou postagem está disponível.

## Limitações verificadas

- Este programa **não** faz diarização de locutor, detecção facial por IA nem correção automática de fala ou refrão. Fazer crop seguindo a pessoa exige evidência e revisão manual.
- O pacote R57 disponível não contém MP4 ou áudio do show, por isso a execução com o vídeo completo deve ser testada no computador que possui o arquivo original.
- A versão Windows com `PyInstaller` é gerável pelo BAT incluído, mas o `.exe` não foi compilado ou homologado neste ambiente Linux.
- Em arquivos longos de alta resolução, a decodificação de cortes finais e a validação podem ser demoradas; não force o encerramento durante o salvamento de `project.json`.

### Legendas com correções

Use `VER SRT PARA REVISÃO` para avaliar palavras no contexto e `IMPORTAR ASS CORRIGIDA` para carregar a legenda editada no seu programa de legendagem. A troca preserva o arquivo original, invalida a aprovação anterior e exige uma nova prévia.
