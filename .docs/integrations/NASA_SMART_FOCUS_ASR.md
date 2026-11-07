# Smart Focus R6 + prévia NASA com legendas ASR visíveis

## Por que a prévia anterior parecia toda em 16:9?

O OpenCV HOG de corpo inteiro é pouco eficaz em astronautas, microgravidade e cenas de cabine. Amostrar até 12 quadros em 74 segundos também perde movimentos de pessoas. A versão atual do Studio investiga até 42 quadros, usa HOG/rosto quando disponível e, **na ausência deles**, cria sugestões de foco em regiões com movimento concentrado. O movimento **não comprova que há uma pessoa** e sempre exige revisão.

O plano de câmera também pode consumir `camera/shared_camera_handoff.json` do ZIP original em `input/analyzer/`. O Curator valida recibo, ZIP, manifesto, SHA256 da fonte e só usa segmentos com `recommended_composition=FOCUS_PERSON_9X16`, `crop_geometrically_valid=true` e geometria normalizada válida. Outras cenas preservam o 16:9 no fundo desfocado.

## Prévia isolada com legendas visíveis

Na raiz do Curator, a partir da `develop` atual, após execução dos testes:

```powershell
$repo = "C:\Users\leone\Documentos\Meus Projetos\LDPORTO_VIDEO_CURATOR"
$workdir = Join-Path $repo "output\projects\NASA_R57_PILOT_fa68b736b2fb"
$inbox = Join-Path $repo "input\analyzer\Eo2bUJcxASI\2131f80ae982b4dc"
& .\.venv\Scripts\python.exe -m ldporto_studio preview --workdir $workdir --id REEL_01 --analyzer-inbox $inbox --draft-captions --require-reframe --editorial-fill
```

Prévia independente em `output/projects/<projeto>/outputs/caption_draft_previews/REEL_01/<execução>/PREVIEW_ASR_DRAFT_540x960.mp4`. Ela contém áudio original, texto e tempos do ASR recebidos e aviso visual **ASR RASCUNHO - CONFERIR AUDIO**.

**Atenção:**
- O comando **não roda um segundo reconhecimento de fala**, não corrige automaticamente erros de transcrição e não aprova legenda. A segunda curadoria deverá escutar o MP4, editar a ASS e revisar a sincronização.
- O arquivo está fora da pasta de prévias aprováveis: **não cria `preview_record`, não muda o projeto, não aprova e não renderiza final**. Os MP4s anteriores ficam intactos.
- `--require-reframe` cancela antes de codificar se não houver nenhuma região segura de foco. Nunca registra um 16:9 desfocado como reframe bem-sucedido.
- Em `CAMERA_PLAN.json` e `RENDER_REPORT.json` ficam o detector, as regiões, a evidência R6, os hashes e os flags de revisão. R6 é recomendação; não é verificação do vídeo final.

## Para legendas finais

Use o `captions-second-check` para inspecionar sincronismo e texto SRT/ASS, ouça e corrija a transcrição de acordo com o áudio real, importe a ASS corrigida, marque explicitamente a conferência humana e produza nova prévia regular. Só depois da aprovação visual/câmera/áudio os renders finais são liberados, com revisão dos direitos.

## Validação Windows

```powershell
python -m unittest discover -s tests -p test_visual_camera.py -v
python -m unittest discover -s tests -p test_r6_camera_evidence.py -v
python -m unittest discover -s tests -p test_caption_second_pass.py -v
```

Os testes com FFmpeg exercitam um MP4 sintético com áudio e ASS reais. Um teste PASS em fixture não significa revisão visual do NASA; esta precisa ser feita abrindo a prévia produzida.


### Gate de cobertura 9:16

Ao usar `--require-reframe`, o Studio exige que **pelo menos 35% da duração total** seja retrato real (crop 9:16) antes de iniciar o FFmpeg. No `CAMERA_PLAN.json` aparece `portrait_coverage_percent`; resultado abaixo do limiar é bloqueado com porcentagem explícita. Isso evita declarar sucesso quando quase todos os segundos continuam no 16:9 desfocado. Não é garantia de qualidade visual: ainda é necessária revisão da prévia completa.


### Interface gráfica

Abra o Curator Studio, selecione o projeto/REEL_01 e clique **PRÉVIA INTELIGENTE + LEGENDAS**. O Studio busca um recebimento R6 com o **mesmo SHA256 da mídia**, muda apenas o layout selecionado para `smart_zoom` (invalidando eventuais aprovações do enquadramento anterior) e prepara uma prévia técnica isolada. Depois clique **ABRIR REVISÃO COM LEGENDAS**. A GUI não confirma transcrição, não marca direitos e não publica; revisão auditiva continua necessária.


### Modo editorial 9:16 para diagnóstico de cobertura baixa

Se o log indicar pouco enquadramento confirmado (ex.: 8,9% no NASA), use **somente na prévia isolada** `--editorial-fill` junto de `--draft-captions --require-reframe`. O Curator preserva as regiões seguras vindas do Analyzer e preenche as lacunas com um **crop central experimental 9:16**, para que o vídeo possa ser visto com legendas. O campo `portrait_coverage_percent` pode atingir 100% por recorte, mas o campo `verified_portrait_coverage_percent` continua com o valor realmente confirmado (8,9% no diagnóstico anterior). Todo o restante é `CENTER_CROP_REVIEW_REQUIRED` e precisa ser visto para evitar cortar astronautas ou elementos laterais. A prévia não é aprovável, não altera direitos nem substitui qualquer MP4 anterior.


## P0 — Legendas amarelas e foco inteligente por cena (7 nov 2026)

- **Legendas no MP4:** o renderizador escreve exclusivamente a cópia `outputs/.../captions.ass` com amarelo opaco `&H0000FFFF`, contorno preto de 5 no PlayRes 1080, negrito e margem inferior 244 (aprox. 122 px na prévia 540×960). Texto, idioma, timestamps, marcas de karaokê e arquivos do Analyzer/Curator não são reescritos. O relatório traz `caption_presentation.preset=YELLOW_HIGH_CONTRAST_V1` e o SHA256 da ASS estilizada. O player pode sobrepor seus controles; observe legendas com o player em tela cheia para julgar contraste e margem.
- **Câmera:** usando o MP4 exato, OpenCV verifica rostos frontais ou de perfil a cada amostra de até 42 quadros, detecta mudanças de cena, e pode seguir suavemente a posição horizontal dentro da mesma tomada. Não usa IA externa, downloads nem modelos pagos. `scene_focus_regions` identifica **sugestões para revisão**, não pessoas confirmadas.
- **Prioridade:** recomendação solo segura do Analyzer > rosto/corpo por cena detectado no Curator > geometria R6 não certificada > recorte central experimental. A cópia gerada pelo modo `--editorial-fill` permanece tecnicamente 9:16; isto **não** prova que todos os rostos ficaram dentro do quadro. Confira `scene_face_focus_percent`, `r6_unverified_guidance_percent`, `center_fallback_percent` e `verified_portrait_coverage_percent` no `CAMERA_PLAN.json`. Se `scene_face_focus_percent=0`, o detector não conseguiu encontrar uma pessoa e o sistema não deve alegar rastreamento inteligente.
- **Fluxo de legenda:** recebe a transcrição ASR do Analyzer na pasta `input/analyzer`; o Curator faz uma segunda checagem de texto e sincronismo. A prévia `--draft-captions` mostra o ASR enquanto ainda **não aprovado**, com watermark obrigatório. Revisão auditiva continua humana; não há segunda transcrição independente automática nem publicação.
- **Preservação:** a prévia antiga, ZIP, análise, renders aprovados, mídia original e commits de outras branches continuam intocados. Os novos resultados ficam sob `outputs/caption_draft_previews/...`.

### Testes

```powershell
python -m unittest discover -s tests -p test_yellow_caption_scene_focus.py -v
python -m unittest discover -s tests -p test_visual_camera.py -v
python -m unittest discover -s tests -p test_r6_camera_evidence.py -v
python -m unittest discover -s tests -p test_editorial_camera_fill.py -v
python -m unittest discover -s tests -p test_caption_second_pass.py -v
```

Os testes de câmera e FFmpeg em fixtures não substituem a conferência da nova prévia NASA de 74 segundos.
