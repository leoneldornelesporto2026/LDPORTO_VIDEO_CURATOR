# L.D.PORTO — Video Curator Studio 1.0

**Programa novo e independente**, desenvolvido para consumir o pacote editorial de execução R57 do Charlie Brown Jr. — Planeta Atlântida 2012. Não altera o `LDPORTO_VIDEO_CURATOR` antigo, nem requer GitHub, Qwen ou Ollama.

## Iniciar no Windows

1. Instale **Python 3.11+** (com Tkinter) e **FFmpeg + FFprobe** no PATH do Windows.
2. Execute `INSTALAR_WINDOWS.bat` (instala Pillow e yt-dlp).
3. Execute `INICIAR_WINDOWS.bat`. A instalação e a GUI usam o mesmo Python do ambiente virtual ativado ou da `.venv` local; no PowerShell use `\.\INSTALAR_WINDOWS.bat` e `\.\INICIAR_WINDOWS.bat`.
4. O exemplo `example/CURADORIA_R57.zip` será carregado e verificado. Se preferir, use **CARREGAR CURADORIA ZIP**.
5. **BAIXAR VÍDEO DO YOUTUBE**: cole a URL HTTPS e clique. O Studio **reaproveita uma cópia já baixada e conferida**, evitando downloads repetidos. Se o SHA256 for diferente mas o ID/duração forem compatíveis, oferece imediatamente a opção de vincular para **gerar prévias de revisão**. Isso não aprova os cortes: cada um exige inspeção do áudio, contexto e câmera. Você também pode usar **VINCULAR MP4 ORIGINAL** para o arquivo exato da análise. Baixe somente conteúdo que você tem direito de utilizar.
6. **SE O SHA256 DIVERGIR:** novos downloads ficam na pasta **`input/videos/` do Curator**, em `input/videos/<video_id>/<hash_pacote>/<tentativa>/`; arquivos antigos em `output/projects/<projeto>/downloads/` continuam aceitos. Clique **USAR DOWNLOAD NAS PRÉVIAS (REVISÃO)**: com o mesmo ID, áudio/vídeo, duração compatível (±3 s) e confirmação explícita, permite prévias com o hash real da cópia baixada. **Isso não prova que o áudio e os timestamps coincidam.** Confira cada prévia; se o trecho estiver deslocado, refaça a análise para o MP4 baixado. O pacote R57 e o SHA original permanecem intactos.
7. Escolha um Reel ou Story, revise início/fim, título, crop e legendas. O padrão usa **fonte horizontal preservada em canvas vertical com fundo desfocado**. Legendas ASR estão desligadas até conferência humana.
8. Gere a prévia em **540×960**, abra e assista, confirme revisão de áudio e câmera e clique **APROVAR PRÉVIA**.
9. Gere o MP4 final em **1080×1920**. Use **EXPORTAR CAPAS + PLANOS** para extrair as 72 capas, arquivos ASS/SRT e metadados.

**Importante:** o ZIP R57 contém 12 Reels, 60 Stories, 72 capas e rascunhos de legendas. Não contém o vídeo original; nada é publicado automaticamente. Os 60 Stories preservam os intervalos cronológicos contínuos, mas cortes de minuto podem cair no meio de fala/música — revise cada um antes de aprovar. Direitos de imagem/áudio permanecem por verificar.

## Recursos

- Verificação integral de SHA256 de todos os membros do ZIP e da mídia original.
- Download **manual** por campo URL, com yt-dlp, progresso, cancelamento, pasta isolada e relatório.
- **Modo de prévia com fonte alternativa:** confirma identidade e duração, nunca troca o SHA da análise e exige revisão de áudio/contexto por corte; ao mudar mídia, invalida aprovações.
- Entrada imutável e projetos em `output/projects/`; vídeos baixados em `input/videos/`, com recibos de integridade.
- Prévia e final usando FFmpeg/H.264 AAC; todas as saídas passam por FFprobe.
- Formato 9:16 com 16:9 integral preservado e fundo desfocado, crop manual, **solo_fit** (pessoa única inteira) ou **smart_zoom** (acompanhamento horizontal suave, com fallback 16:9 quando não há detecção segura).
- Card branco arredondado **L.D.PORTO.OFICIAL / AO VIVO**, título preto viral, detalhe amarelo e rodapé, exibido nos primeiros 3,2 segundos.
- Legenda em ASS estilo amarelo/branco só quando explicitamente revisada.
- Capas originais do R57 exportáveis e geração opcional de nova capa baseada no MP4 verificado.
- Aprovação por *hash da prévia + plano de edição + fonte + versão do renderer*; editar vídeo invalida autorização anterior.
- Reels com normalização de áudio e fades muito curtos; Stories sem fade para preservar a continuidade.
- Finais somente após a aprovação da prévia. Relatório de origem e `EXPORT_MANIFEST.json`; nunca presume autorização de publicação.

O estado `FINAL_READY_REVIEW_RIGHTS` significa que o MP4 final está gerado, **não** que o conteúdo esteja liberado para postar.

## Arquitetura

- `ldporto_studio/core.py` — contrato R57, segurança, integridade, edições, revisão, histórico e aprovações.
- `ldporto_studio/rendering.py` — FFmpeg/FFprobe, composição, títulos, legendas e capas.
- `ldporto_studio/gui.py` — interface desktop Tkinter.
- `ldporto_studio/__main__.py` — automação CLI opcional.
- `example/CURADORIA_R57.zip` — pacote editorial original, sem alterações.
- `tests/` — testes com vídeo sintético + validação real do pacote R57.
- `docs/INSTALACAO_WINDOWS.md` — requisitos, limitações e solução de problemas.

## Comandos CLI

```bat
py -3 -m ldporto_studio import --zip "example\CURADORIA_R57.zip" --workdir "C:\curator_projects\CBJR"
py -3 -m ldporto_studio download --workdir "C:\curator_projects\CBJR" --url "https://www.youtube.com/watch?v=aUgESZsOGmY"
py -3 -m ldporto_studio review-download --workdir "C:\curator_projects\CBJR" --confirm-preview-review
py -3 -m ldporto_studio associate --workdir "C:\curator_projects\CBJR" --media "D:\Videos\CBJR_ORIGINAL.mp4"
py -3 -m ldporto_studio list --workdir "C:\curator_projects\CBJR" --kind reels
py -3 -m ldporto_studio preview --workdir "C:\curator_projects\CBJR" --id REEL_01
py -3 -m ldporto_studio approve --workdir "C:\curator_projects\CBJR" --id REEL_01 --watched --audio-ok --camera-ok
py -3 -m ldporto_studio final --workdir "C:\curator_projects\CBJR" --id REEL_01
py -3 -m ldporto_studio assets --workdir "C:\curator_projects\CBJR"
```

A aprovação CLI só deve ser executada depois que **uma pessoa** realmente assistiu e revisou a prévia. `--watched` não substitui essa verificação.

Teste com `py -3 -m unittest discover -s tests -v`.

### Revisar ou substituir legendas

A opção **VER SRT PARA REVISÃO** abre o rascunho de texto. Corrija e sincronize a legenda no editor da sua preferência, exporte em `.ass` UTF-8, e use **IMPORTAR ASS CORRIGIDA**. A nova legenda fica versionada fora do ZIP original e desativa a aprovação anterior; após conferir o áudio, marque **Conferi transcrição e áudio** e **Incluir karaokê ASS**, salve e gere nova prévia.

## Saídas locais: tudo dentro do projeto original

O código fica na pasta `LDPORTO_VIDEO_CURATOR`. Projetos e MP4s renderizados ficam em **`output/projects/<projeto>/`**, e vídeos baixados ficam em **`input/videos/` do Curator**. `input/` contém ZIPs de análise recebidos localmente. Só roteiros textuais em **`output/scripts/` ou `input/scripts/`** entram no Git; todo o restante é ignorado.

Projetos antigos de `C:\Users\leone\Videos\LDPORTO_CURATOR_STUDIO_PROJECTS` **não são movidos automaticamente**. Para preservar o Reel já gerado, clique **IMPORTAR PROJETO ANTIGO** e escolha a pasta com `project.json`. O Curator copia para `output/projects`, reconcilia os caminhos internos de downloads e mantém a pasta original como backup. Também é possível:

```powershell
python -m ldporto_studio adopt-project --source "C:\Users\leone\Videos\LDPORTO_CURATOR_STUDIO_PROJECTS\CURADORIA_R57_69769168cf"
```

Depois, basta abrir o exemplo R57: a GUI encontrará o projeto existente em `output/projects/`. Caso já exista um projeto com esse nome, a cópia é recusada, **sem sobrescrever**. Confira o espaço livre antes de importar arquivos de vídeo grandes.

## Padrão viral R58 — câmera + capas do vídeo real

Os novos modos de edição são:
- **preserve**: fonte 16:9 inteira no centro de um canvas 9:16, com fundo desfocado. Ideal para palco aberto, banda ou câmera não confiável.
- **solo_fit**: procura pessoa única *de corpo inteiro* nas amostras; só recorta se ela couber na janela vertical com margens. Caso contrário preserva o 16:9.
- **smart_zoom**: usa OpenCV (HOG corporal + verificação de múltiplos rostos) para acompanhar horizontalmente uma pessoa inteira com suavização. Em grupo, ambiguidade ou detecção inconsistente, preserva o 16:9. **Não é rastreamento perfeito de pessoas:** iluminação, movimento de câmera, instrumentos e multidões dificultam a detecção. Revisão humana é indispensável.
- **center_crop**: recorte central manual já existente.

A tela oferece **APLICAR SMART ZOOM AOS 12 REELS** (não altera os Stories) e **GERAR 72 CAPAS PREMIUM DO MP4**. O card dos títulos e das capas segue a referência aprovada: caixa branca com borda amarela, `L.D.PORTO.OFICIAL`, indicador `AO VIVO`, título preto em caixa alta, sublinhado dourado e gênero no rodapé.

As novas capas usam quadros reais da mídia associada e são salvas em `output/projects/<projeto>/exports/covers_premium/` com versionamento por conteúdo. Cada prévia também cria uma `CAPA_PREMIUM.png` e, ao usar modo inteligente, um `CAMERA_PLAN.json`. O plano de câmera aprovado na prévia é reutilizado no final correspondente; troca de modo ou implementação invalida aprovações antigas.

**CLI PowerShell (depois de associar o MP4):**

```powershell
python -m ldporto_studio smart-preset --workdir ".\output\projects\CURADORIA_R57_69769168cf" --kind reels --mode smart_zoom --confirm
python -m ldporto_studio preview --workdir ".\output\projects\CURADORIA_R57_69769168cf" --id REEL_01
python -m ldporto_studio covers-premium --workdir ".\output\projects\CURADORIA_R57_69769168cf" --kind all
```

O ZIP R57 original, os vídeos anteriores e os projetos locais são preservados. Não há aprovação editorial ou publicação automática.

## Inbox do Analyzer — evidências para segunda curadoria

O Analyzer poderá entregar o ZIP nativo em `input/analyzer/<video_id>/<run_id>/`.
O conteúdo de `input/analyzer/` é local e ignorado pelo Git; apenas `input/scripts/` é versionável.
Esse ZIP **não é** o formato editorial R57 importável pela interface atual.
Para inspecionar integridade e recibo, sem importar, executar:

```powershell
python -m ldporto_studio.analyzer_inbox --path ".\input\analyzer\<video_id>\<run_id>"
```

O resultado `VALID` atesta somente a integridade da cópia e das referências examinadas.
O estado permanece `CURATOR_IMPORT_PENDING`, até existir um adaptador de conversão
validado separadamente. Não clicar `CARREGAR CURADORIA ZIP` com o ZIP do Analyzer.
A segunda curadoria com ChatGPT produzirá depois um plano editorial executável,
sem presumir aprovação ou publicar automaticamente.

## Biblioteca de shows — entrada automática Analyzer → Curator

Ao abrir, o Studio **não importa automaticamente o Charlie Brown Jr.**: oferece o seletor **VÍDEOS JÁ PROCESSADOS**, alimentado pelas pastas `input/` e `output/projects/`. O botão **ATUALIZAR INPUT** atualiza a lista sem reiniciar o Windows; **ABRIR / SELECIONAR CORTES** abre o show escolhido e revela os Reels e Stories existentes na tabela. Projetos antigos continuam acessíveis sem reimportar ou rebaixar MP4.

- `output/projects/<projeto>/` → **PROJETO EM ANDAMENTO**: abre a curadoria atual preservando downloads, edições, câmera, capas e prévias.
- `input/curadorias/<show>/<run_id>/*.zip` ou outro ZIP R57 reconhecido em `input/` → **CURADORIA PRONTA PARA IMPORTAR**: valida integralmente no momento da importação e cria/reabre projeto em `output/projects/`.
- `input/analyzer/<video_id>/<run_id>/*.zip` → **ANALYZER R6 — AGUARDANDO SEGUNDA CURADORIA**: mostra título real, candidatos e run ID, mas **não** interpreta esse pacote como o formato editorial R57. É necessário produzir uma segunda curadoria compatível.
- Arquivos MP4 sem evidências de análise não aparecem como programas processados. Um novo show, como CPM 22 ao vivo, aparecerá **somente após existir um pacote válido ou projeto real**, não há bandas inventadas no catálogo.

Os ZIPs de entrada ficam locais em `input/analyzer/`, ignorados pelo Git. Os renders, capas e estado operacional ficam em `output/projects/`, também ignorados. Somente scripts de edição em `input/scripts/` e `output/scripts/` são versionáveis. O scanner lê apenas metadados JSON limitados dos ZIPs; não extrai nem executa arquivos recebidos. A importação R57 executa a validação SHA256 integral já existente. Os módulos `smart_camera.py`, `visual_style.py` e `rendering.py` continuam sendo o único motor dos modos `preserve`, `center_crop`, `solo_fit` e `smart_zoom`.

Consultar catálogo sem abrir GUI:

```powershell
python -m ldporto_studio catalog
```

## Armazenamento local de downloads e Git somente de roteiros

O botão **BAIXAR VÍDEO DO YOUTUBE** salva novos arquivos na pasta **`input/videos/` do Curator**, sob `LDPORTO_VIDEO_CURATOR/<video_id>/<source_package_sha>/...`. Essa pasta respeita o local de Vídeos configurado no Windows. Downloads antigos guardados dentro de `output/projects/.../downloads/` continuam reconhecidos por SHA256, sem migração nem novo download obrigatório.

O Curator mantém `input/analyzer/` como caixa de entrada de ZIPs e `output/projects/` como trabalho local. Apenas os roteiros sem mídia são registrados pelo Git em `output/scripts/` (ou `input/scripts/`): títulos, timestamps, layouts, `smart_zoom`, `solo_fit`, planos de câmera revisáveis e estados das legendas. Nada de vídeos, áudio, imagens, ZIPs ou o arquivo operacional `project.json`.

Para exportar um roteiro pelo próprio Studio, clique **EXPORTAR ROTEIRO PARA GIT (SEM VÍDEO)** ou use:

```powershell
python -m ldporto_studio export-script --workdir ".\output\projects\CURADORIA_R57_69769168cf"
git add output/scripts input/scripts
python scripts/check_git_review_payload.py
git diff --cached --stat
```

O roteiro tem nome de revisão baseado no conteúdo; versões antigas não são sobrescritas. Não ocorre commit ou push automático. O histórico Git pode ser consultado posteriormente para comparar escolhas editoriais; não é uma cópia dos arquivos de vídeo na memória do ChatGPT.

## Localização dos vídeos (definição atual)

**Novos downloads de vídeo:** `input/videos/<youtube_video_id>/<hash_pacote>/<tentativa>/source.mp4`. Essa subpasta fica na pasta original `LDPORTO_VIDEO_CURATOR` e é explicitamente excluída pelo `.gitignore` como `/input/videos/`. Nunca executar `git add -f input/videos`.

**Vídeos existentes:** downloads anteriores em `output/projects/.../downloads/` ou na pasta Vídeos do Windows continuam utilizáveis, desde que o histórico do projeto, o manifesto e o SHA256 sejam válidos. Nada é movido nem duplicado automaticamente. O botão de download reaproveita o arquivo verificado, sem refazer o download. `output/projects/` mantém prévias/renders locais; somente roteiros em `input/scripts/` e `output/scripts/` são versionáveis.

## P1 — Segunda curadoria do ZIP R6 do Analyzer (seletor de candidatos)

No catálogo do Curator, selecione **ANALYZER R6 — AGUARDANDO SEGUNDA CURADORIA** e clique **ABRIR / SELECIONAR CORTES**. O Studio agora confere recibo, SHA256, manifesto completo, índice de evidências e abre a janela **Segunda curadoria R6**, sem tocar nos projetos editoriais existentes. A janela apresenta **somente os candidatos realmente exportados** pelo Analyzer, com rank, tempos, transcrição, restrições de conteúdo, estados de legenda e pendências reais. Você escolhe os trechos (Ctrl/Shift), pode ajustar título e `preserve`/`solo_fit`/`smart_zoom`/`center_crop` individualmente e clica **EXPORTAR SELECIONADOS — SOMENTE ROTEIRO JSON**.

O roteiro fica em `output/scripts/<show>_<sha>/R6_REVIEW_<hash>.json`, com revisões imutáveis por conteúdo. O script contém títulos, timestamps, vínculo com `candidate_id`, escolha de câmera, alertas editoriais e proveniência do ZIP. **Não contém MP4, áudio, imagem nem caminhos absolutos.** Nenhuma decisão é aprovada, não há mídia renderizada, e os 12 Reels/60 Stories R57 anteriores **não são sobrescritos**. Caso o Analyzer entregue zero Stories, o roteiro preserva esse zero; não fabrica uma sequência de 60.

Para inspecionar os candidatos sem GUI:

```powershell
python -m ldporto_studio r6-review --inbox ".\input\analyzer\aUgESZsOGmY\f8b424b9fc26c791"
```

Para exportar **apenas IDs explicitamente escolhidos** (substitua IDs pelos listados acima):

```powershell
python -m ldporto_studio r6-draft --inbox ".\input\analyzer\aUgESZsOGmY\f8b424b9fc26c791" --ids CANDIDATO_ID_1 CANDIDATO_ID_2 --mode preserve --confirm-review-draft
```

**Limitação técnica importante:** o roteiro R6 é uma *seleção para revisão*, não um ZIP de execução R57. O renderizador R57 exige assets de thumbnail, ASS/SRT revisados, Stories contínuos, manifestos e vinculação de mídia compatíveis. O próximo desenvolvimento é promover um roteiro selecionado a contrato renderizável, depois de validar esses insumos (sem inventá-los).

## P1.1 — Filtro de cortes R6 e pré-validação sem render

Com o show aberto na janela **Segunda curadoria R6**, use **Buscar trecho / fala / ID**, o filtro de candidatos e **Ocultar intervalos repetidos (só na tela)**. O aplicativo mantém o catálogo integral, com todos os IDs e advertências do Analyzer. Nenhum candidato é escolhido automaticamente. Use Ctrl/Shift para destacar na tabela e clique **MARCAR SELECIONADOS** para colocá-los no roteiro; trocas de filtro não perdem os marcados. Escolha um candidato isolado para editar título, `preserve`, `solo_fit`, `smart_zoom` ou `center_crop`, salve a alteração e exporte **EXPORTAR MARCADOS — ROTEIRO JSON**.

O painel informa número de intervalos repetidos, títulos pendentes, candidatos não elegíveis e quantos realmente foram marcados. Há **ABRIR PASTA DO ROTEIRO** depois da exportação. Arquivos `R6_REVIEW_*.json` só são produzidos após seleção e confirmação explícitas: abrir/fechar a GUI sozinho não gera um roteiro.

Para verificar o pacote sem imprimir centenas de linhas:

```powershell
python -m ldporto_studio r6-review --inbox ".\input\analyzer\aUgESZsOGmY\f8b424b9fc26c791" --summary
```

Depois de exportar um roteiro, confirme suas referências usando:

```powershell
$draft = Get-ChildItem ".\output\scripts" -Recurse -File -Filter "R6_REVIEW_*.json" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $draft) { throw "Nenhum roteiro R6 exportado pela seleção." }
python -m ldporto_studio r6-preflight --inbox ".\input\analyzer\aUgESZsOGmY\f8b424b9fc26c791" --draft $draft.FullName
```

A pré-validação reabre o ZIP real, verifica SHA256/identidade do projeto, IDs selecionados, timestamps, alertas, intervalos duplicados/sobrepostos e aprovações indevidas. Com `--media <arquivo.mp4>` opcional, calcula o SHA256 real da mídia (sem copiá-la) e avisa quando **não coincide** com o vídeo que o Analyzer analisou. **Mesmo com SHA igual, o relatório nunca declara `render_ready=true` ou publicação aprovada.** A conversão do roteiro em pacote renderizável e a homologação de câmera/legendas permanecem tarefas separadas.

## Teste automático R6 — sem digitar IDs e sem abrir a GUI

Quando o Analyzer entrega os candidatos com a `shortlist_count=0` (ou todos pendentes), o Curator **não deve aprovar nem afirmar que escolheu os melhores cortes**. Para comprovar o fluxo sem perguntar IDs no PowerShell, use:

```powershell
python -m ldporto_studio r6-smoke --inbox ".\input\analyzer\aUgESZsOGmY\f8b424b9fc26c791"
```

O comando escolhe **2 candidatos reais apenas para teste técnico**, sem sobreposição de intervalo, preferindo trechos de 15–90 segundos, não comerciais e com menos alertas quando existirem. Ele gera um roteiro com `selection_origin=AUTOMATED_TECHNICAL_SMOKE_TEST_ONLY` em `output/r6_smoke/<source_sha>/<zip_sha>/SMOKE_R6_<hash>.json`; essa pasta é **ignorada pelo Git**. Em seguida executa automaticamente o preflight completo contra o ZIP e imprime `SMOKE_PASSED_WITH_PENDING_HUMAN_REVIEWS` com os IDs usados, caminho de arquivo e avisos.

O roteiro de smoke **não é uma escolha editorial**, não é `R6_REVIEW_*.json`, não altera projetos existentes nem mídia, não produz prévias/finais e mantém `render_ready=false`. Para repetir o teste, executar o mesmo comando é idempotente, sem sobrescrever revisões anteriores. Testar de 1 a 5 intervalos com `--count 3` quando houver duração suficiente.

**Atenção à execução em PowerShell 5.1:** erros `throw` lançados ao colar trechos separados podem deixar o console disponível para os comandos seguintes. Use um **bloco único** com checagem de `$LASTEXITCODE`; nunca executar preflight com `$draft` vazio. O `r6-smoke` já executa exportação e pré-validação no mesmo comando, eliminando essa fonte de erro.

## P2 — localizar mídia já existente do Analyzer, sem redownload

O pacote R6 do Analyzer preserva o SHA256 do arquivo audiovisual original. Um teste `r6-smoke` bem-sucedido **não significa que o vídeo original esteja associado**; a saída `media_identity: NOT_CHECKED` exige esta verificação antes das prévias.

Execute sem digitar IDs ou baixar mídia:

```powershell
python -m ldporto_studio r6-media-audit --inbox ".\input\analyzer\aUgESZsOGmY\f8b424b9fc26c791"
```

O diagnóstico procura arquivos de vídeo **somente em diretórios locais conhecidos e com limites de varredura**, priorizando `input/videos/<video_id>/`, os downloads antigos `Vídeos/LDPORTO_VIDEO_CURATOR/<video_id>/` e pastas de tentativas dos projetos anteriores em `output/projects/<projeto>/downloads/attempts/`. Abre os candidatos localmente, calcula SHA256 e classifica:
- `EXACT_SOURCE_FOUND`: pelo menos um arquivo tem os mesmos bytes (SHA256) da fonte analisada;
- `ALTERNATE_MEDIA_ONLY_REVIEW_REQUIRED`: há vídeo local, mas **nenhum** corresponde ao SHA256 original. Mesmo vídeo/URL/duração não comprovam sincronismo; os timestamps R6 não são liberados para render automático;
- `NO_MANAGED_MEDIA_FOUND`: não encontrou vídeo nos diretórios gerenciados; informe manualmente um arquivo conhecido com `--media "C:\...\original.mp4"`, sem mover/copiar.

A busca é limitada a 12 arquivos verificados e reporta `scan_truncated` se atingir o limite. Não varre a unidade C inteira. Não altera recibos, aprovação, `project.json`, R57, arquivos de mídia nem o estado dos cortes. `render_ready` e `human_approved` permanecem **false** independentemente do resultado. A associação controlada do vídeo e uma prévia técnica isolada serão tratadas depois que esta auditoria identificar uma fonte segura.

## Piloto completo com vídeo real — prévia técnica R6

O operador do Analyzer `scripts/windows/testing/PILOTO_FULL_DEFAULTS.ps1` executa as **duas suítes completas** antes de analisar vídeo novo. O Curator acrescenta `r6-preview-smoke`: dado o ZIP Analyzer validado e o arquivo original com **SHA256 exatamente igual**, escolhe um candidato somente para teste e produz **no máximo 8 segundos** de vídeo com áudio e quadro original preservado dentro de 360×640, em `output/r6_preview_smoke/` (ignorado pelo Git).

```powershell
python -m ldporto_studio r6-preview-smoke --inbox ".\\input\\analyzer\\<video_id>\\<run_id>" --media "C:\\...\\fonte_exata.mp4" --seconds 6 --confirm-preview-test
```

Esta saída é **somente uma prévia técnica de integração**: não aplica `smart_zoom`, não finge legendas/câmera revisadas, não é um Reel completo, não gera um pacote editorial R57, não aprova nem publica. O status será `TECHNICAL_PREVIEW_REVIEW_REQUIRED`; `render_ready=false`, `publication_ready=false`, `human_approved=false`. O arquivo tem recibo JSON SHA256, reexecução idempotente e recusa de arquivo já existente divergente.

O próximo desenvolvimento P2 real continua sendo o adaptador R6 → plano/ativos R57, com verificação de áudio/câmera/transcrição, Stories apenas quando há evidência, prévias finais e aprovação humana explícita. Não confundir o piloto de vídeo com a homologação editorial.


## Ponte editorial R6 → R57: plano de preparação (P1, somente JSON)

O pacote Analyzer R6 **não** satisfaz diretamente o contrato de importação R57: o Curator exige um plano com pelo menos um Reel e Stories contínuos cobrindo a mídia inteira, além de thumbnails e legendas ASS/SRT reais e manifestos verificados. Quando o Analyzer entrega zero Stories (como no piloto NASA), **nenhum Story é fabricado**. A nova ponte valida o recibo/ZIP original, exige um roteiro R6 exportado após seleção explícita de candidatos, conserva IDs e timestamps e gera um checklist por Reel com a estrutura de assets esperada. Não cria ZIP R57, projeto, capa, legenda, render, aprovação ou publicação.

Depois de exportar `R6_REVIEW_*.json` pela janela de Segunda curadoria, clique **PLANO R6 → R57 (PENDÊNCIAS)**. O plano fica em `output/r6_bridge/<sha-prefix>/R6_TO_R57_PLAN_<fingerprint>.json` (ignorado pelo Git), é idempotente por conteúdo e guarda hashes de proveniência, mas não caminhos locais absolutos.

Para visualizar apenas as pendências (sem criar arquivo):

```powershell
python -m ldporto_studio r6-r57-plan --inbox ".\input\analyzer\<video_id>\<run_id>" --draft ".\output\scripts\<show>\R6_REVIEW_<hash>.json"
```

Para persistir o plano, acrescentar `--save`. Para confirmar a identidade da fonte audiovisual já existente, informar `--media "C:\...\original.mp4"`; SHA divergente ou ausente mantém o bloqueio. O comando nunca importa a curadoria para `Project`, nem trata o smoke automático como escolha editorial. Antes da futura conversão executável, faltam o roteiro de Stories definido por pessoa, assets de legenda/capa efetivamente revisados e validação formal do ZIP R57 com `CuradoriaPackage`.


## Filtro da biblioteca: revisão vs. diagnóstico (06/11/2026)

O catálogo completo permanece disponível e **nenhum arquivo local é excluído**. A GUI prioriza por padrão projetos R57 existentes e pacotes R6 com pelo menos um candidato e um SHA256 de origem plausível; ZIPs com zero candidatos, SHA ausente/obviamente sintético, e registros inválidos são ocultados **somente na seleção**. Marque **Mostrar todos (inclui testes)** para exibir os demais. O filtro é heurístico, não validação editorial, nem garantia de origem real: o Analyzer R6 só abre após `read_analyzer_review` verificar integralmente o ZIP/recibo.

Para uma listagem reduzida via CLI:
```powershell
python -m ldporto_studio catalog --reviewable
```
Para a listagem integral, inclusive testes locais:
```powershell
python -m ldporto_studio catalog
```
O resultado informa `count`, `total_discovered` e `hidden_from_view`. A consulta não modifica projetos, inbox nem Git. No piloto de 06/11/2026, a listagem integral continha 52 entradas: 1 projeto CBJR existente, 3 pacotes R6 reais (2 NASA, 1 CBJR) e 48 registros de testes/diagnósticos, preservados no disco.


## P1.2 — Proposta de timeline Stories baseada somente na duração (sem aprovação)

O novo `r6-story-propose` usa **somente** o SHA e a duração real de um R6 validado e a seleção editorial de Reels já exportada. Divide a fonte em janelas técnicas contínuas com no máximo 60 segundos, mas **não inventa Stories do Analyzer, eventos de cena ou legendas**. São sugestões para edição, não seleção/curadoria final. No vídeo NASA (158,654 segundos), a divisão técnica corresponde a **3 janelas** contíguas, cada uma com cerca de 52,9 segundos. `source_story_candidate_count=0` permanece zero.

Após selecionar os cortes na GUI e exportar o roteiro R6, o botão **PROPOR STORIES (SEM APROVAR)** gera um JSON ignorado pelo Git em `output/r6_bridge/<sha-prefix>/R6_STORY_PROPOSAL_<hash>.json`, idempotente por conteúdo. O botão **PLANO R6 → R57 (PENDÊNCIAS)** pode vincular a proposta à lista de lacunas R57, sem torná-la importável.

CLI somente leitura:
```powershell
python -m ldporto_studio r6-story-propose --inbox ".\input\analyzer\<video_id>\<run_id>" --draft ".\output\scripts\<show>\R6_REVIEW_<hash>.json"
```

Acrescente `--save` para persistir a proposta local. A revisão posterior pode ajustar os intervalos no JSON, mas `r6-r57-plan --story-proposal "caminho.json"` só aceita janelas ordenadas, não sobrepostas, cobrindo a fonte inteira, cada uma de até 60 segundos, e com proveniência SHA/runs correta. Flags de aprovação falsificadas são rejeitadas. Mesmo com a timeline proposta validada, continuam bloqueados os assets reais (capa/ASS/SRT), a verificação editorial das janelas e as aprovações de prévias/direitos; `r57_story_slots=[]`, `r57_import_ready=false` e nenhum ZIP executável é produzido.


## P1.3 — Checklist de assets reais do Analyzer R6

Depois de exportar a seleção R6 e a proposta de Stories, a janela **Segunda curadoria** oferece **CHECKLIST ASSETS R57**. O template é salvo em `output/r6_bridge/<sha-prefix>/R6_ASSETS_<hash>.json` e contém um Reel/Story por linha, com caminhos `thumbnail`, `caption_ass`, `caption_srt` vazios por padrão. Os 3 arquivos devem ser **arquivos reais** fornecidos pelo operador, com paths relativos a uma pasta local escolhida.

CLI de inspeção (somente leitura):
```powershell
python -m ldporto_studio r6-assets --inbox "input/analyzer/<video_id>/<run_id>" --draft "output/scripts/<show>/R6_REVIEW_<hash>.json" --story-proposal "output/r6_bridge/<sha>/R6_STORY_PROPOSAL_<hash>.json"
```

Para salvar o template, inclua `--save-template`. Depois de preenchê-lo, acrescente `--bindings <template_preenchido.json> --assets-root <pasta_dos_arquivos>` para a auditoria. Ela verifica caminho relativo seguro, ausência de junctions, imagem PNG/JPEG válida, ASS com eventos, SRT com timestamps, SHA256 e proveniência dos cortes. **Validade estrutural não significa sincronização de legendas, aprovação das cenas, dos direitos ou do render**. Nenhum ZIP ou MP4 é gerado.
