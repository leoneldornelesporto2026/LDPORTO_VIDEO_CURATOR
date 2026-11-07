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
& .\.venv\Scripts\python.exe -m ldporto_studio preview --workdir $workdir --id REEL_01 --analyzer-inbox $inbox --draft-captions --require-reframe
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
