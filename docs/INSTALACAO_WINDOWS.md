# Instalação e operação segura no Windows

## Pré-requisitos

- Windows 10/11, Python 3.11 ou mais recente com Tkinter disponível.
- FFmpeg e FFprobe no PATH. Confira no CMD: `ffmpeg -version` e `ffprobe -version`.
- Pillow, yt-dlp e OpenCV headless (`INSTALAR_WINDOWS.bat`). O yt-dlp pode precisar ser atualizado quando o YouTube alterar os formatos; falhas de acesso não são contornadas automaticamente.
- Espaço livre suficiente para prévias e finais: vídeo 1080×1920 pode consumir centenas de MB.

Para instalar o FFmpeg via winget quando disponível: `winget install --id Gyan.FFmpeg -e`. Feche/reabra o terminal após instalar para atualizar o PATH. Não use a opção de associar mídia diferente da fonte analisada: mesmo vídeo reencodificado tem outro hash e precisa ser reanalisado/retificado na origem.

## Operação

1. Use a pasta original do código `LDPORTO_VIDEO_CURATOR`, branch `develop`. Não crie worktrees/clones adicionais.
2. No PowerShell, execute `\.\INSTALAR_WINDOWS.bat` e `\.\INICIAR_WINDOWS.bat`. Os dois scripts escolhem o mesmo interpretador Python, dando prioridade ao ambiente virtual ativado ou `.venv` da raiz.
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
- **Saídas**: todos os projetos, downloads, prévias, finais e capas ficam em `output/projects/` dentro da raiz do código, com `output/` ignorado pelo Git. Cada execução usa uma pasta isolada; falhas preservam logs. O render final é bloqueado sem aprovação da prévia atual.
- **Direitos**: aprovação do preview não comprova direitos; nenhum upload automático ou postagem está disponível.

## Limitações verificadas

- Este programa **não** faz diarização de locutor, detecção facial por IA nem correção automática de fala ou refrão. Fazer crop seguindo a pessoa exige evidência e revisão manual.
- O pacote R57 disponível não contém MP4 ou áudio do show, por isso a execução com o vídeo completo deve ser testada no computador que possui o arquivo original.
- A versão Windows com `PyInstaller` é gerável pelo BAT incluído, mas o `.exe` não foi compilado ou homologado neste ambiente Linux.
- Em arquivos longos de alta resolução, a decodificação de cortes finais e a validação podem ser demoradas; não force o encerramento durante o salvamento de `project.json`.

### Legendas com correções

Use `VER SRT PARA REVISÃO` para avaliar palavras no contexto e `IMPORTAR ASS CORRIGIDA` para carregar a legenda editada no seu programa de legendagem. A troca preserva o arquivo original, invalida a aprovação anterior e exige uma nova prévia.

## Importar trabalhos anteriores sem criar novos workspaces de código

A pasta antiga `Videos/LDPORTO_CURATOR_STUDIO_PROJECTS` ainda existe como backup. Na GUI, use **IMPORTAR PROJETO ANTIGO** e selecione `CURADORIA_R57_69769168cf`. Isso **copia**, não move: `project.json`, vídeos, downloads e relatórios são transferidos para a pasta `output/projects/CURADORIA_R57_69769168cf` do código aberto e caminhos internos são atualizados. O comando equivalente no PowerShell é:

```powershell
python -m ldporto_studio adopt-project --source "C:\Users\leone\Videos\LDPORTO_CURATOR_STUDIO_PROJECTS\CURADORIA_R57_69769168cf"
```

Não exclua a cópia de origem antes de validar que todos os vídeos renderizados e relatórios abrem na cópia. A importação recusa nomes já existentes.

## Download já salvo e SHA256 diferente

Quando o YouTube entrega outra codificação, o botão **BAIXAR VÍDEO DO YOUTUBE** verifica se já existe uma cópia íntegra do mesmo vídeo dentro de `output/projects/<projeto>/downloads/attempts/`, validando o manifesto e o hash real. **Não baixa novamente** quando encontra arquivo válido. Com o mesmo ID e duração compatível, a interface oferece vincular a fonte para **prévia de revisão**, mediante sua confirmação. O SHA256 original do Analyzer permanece inalterado. Mesmo ID e duração não provam sincronização; revise cada corte antes de aprovar o final. Se a duração divergir, é necessária reanálise do MP4.

## Visual R58 e enquadramento conservador

Use o seletor **Enquadramento**: `preserve`, `center_crop`, `solo_fit` ou `smart_zoom`. Os modos automáticos inspecionam amostras de quadros com OpenCV e geram `CAMERA_PLAN.json` dentro de cada prévia. Uma pessoa de corpo inteiro com margem lateral permite crop; cenas com banda, mais de um rosto, cortes bruscos ou baixa confiança caem para composição 16:9 completa (fundo desfocado). Esse detector clássico é limitado: nenhum enquadramento é declarado aprovado sem a inspeção visual de uma pessoa.

O botão **APLICAR SMART ZOOM AOS 12 REELS** altera somente configurações locais de edição (não o ZIP), podendo invalidar prévias e aprovações anteriores. **GERAR 72 CAPAS PREMIUM DO MP4** usa quadros da mídia associada e escreve em `output/projects/<id>/exports/covers_premium`, ignorado pelo Git. As capas originais R57 são preservadas.

Reinstale dependências com `python -m pip install -r .\requirements.txt` na mesma `.venv` que executa o programa. Testes: `python -m unittest discover -s tests -v`. A compatibilidade com os momentos reais do show e a validade das legendas ainda exigem inspeção no Windows.

## Selecionar shows processados em input/

A GUI agora abre um seletor de shows detectados. Coloque os ZIPs do Analyzer em `input/analyzer/<video_id>/<run_id>/` e, quando a segunda curadoria estiver pronta, coloque o ZIP R57 compatível em qualquer subpasta de `input/`. A pasta é criada automaticamente e ignorada pelo Git. Clique **ATUALIZAR INPUT**, selecione o pacote/show e depois **ABRIR / SELECIONAR CORTES**.

Quando a escolha for um projeto de `output/projects/`, o Studio abre os Reels/Stories já processados, mantendo todos os MP4s e aprovações de revisão anteriores. Quando for um ZIP do Analyzer R6, ele identifica o show e seus candidatos, mas não renderiza: depende da segunda curadoria compatível. Nenhum nome de banda é adicionado manualmente à lista.

O catálogo somente examina metadados limitados em ZIPs e não os extrai. Execute `python -m ldporto_studio catalog` para diagnóstico. Não mova/deleta os projetos existentes ao organizar a biblioteca; `input/` e `output/` não são versionados.
