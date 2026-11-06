# OUTPUT — Projetos locais e roteiros versionáveis

- `output/projects/`: projetos reais, renders, planos temporários, miniaturas e relatórios de trabalho. **Tudo permanece local, ignorado pelo Git.**
- `output/scripts/<show>_<sha>/REVISION_<hash>.json`: **somente roteiros de curadoria**, gerados pelo botão **EXPORTAR ROTEIRO PARA GIT (SEM VÍDEO)**. Esta é a única subpasta de output destinada a commits.
- Novos vídeos baixados ficam em `input/videos/`, ignorados pelo Git; os anteriores salvos em Vídeos do Windows ou `output/projects/...` continuam reconhecidos e não são movidos automaticamente.

Para gerar/compartilhar o roteiro:

```powershell
python -m ldporto_studio export-script --workdir ".\\output\\projects\\CURADORIA_R57_69769168cf"
git add output/scripts input/scripts
python scripts/check_git_review_payload.py
git diff --cached --stat
```

Somente com o resultado conferido faça commit/push. O roteiro contém títulos, timestamps, sequências, escolhas e planos de câmera, sem arquivo audiovisual ou caminho absoluto de Windows. Git permite recuperar/revisar versões do roteiro posteriormente, mas não armazena vídeos em memória do ChatGPT.

## Scripts da segunda curadoria R6

Uma seleção de candidatos do Analyzer gera `output/scripts/<show>_<sha>/R6_REVIEW_<digest>.json` com proveniência, tempos de corte, títulos e modo de câmera. Mesmo conteúdo não duplica revisão; alterações criam novo digest. O ZIP R57 existente, o estado de projetos, MP4, prévias e aprovações anteriores são preservados. Roteiros R6 continuam `CURATOR_IMPORT_PENDING` até haver um pacote renderizável validado.

## Confirmação de exportação e inspeção

`R6_REVIEW_*.json` só aparece em `output/scripts/<show>_<sha>/` após marcar candidatos e clicar **EXPORTAR MARCADOS — ROTEIRO JSON**. A abertura da GUI ou uma inspeção `r6-review` não gera roteiros. Os arquivos são idempotentes por conteúdo, sem duplicar MP4.

Use `python -m ldporto_studio r6-preflight --inbox <entrega> --draft <roteiro>` para conferir integridade, IDs e tempos, além de alertas de duplicidade, câmera, áudio e legendas. A pré-validação preserva `render_ready=false`.

## R6 smoke-test técnico automático

`output/r6_smoke/` é **local e não versionado** (ignorado por `.gitignore`). Contém somente `SMOKE_R6_*.json` produzidos por `python -m ldporto_studio r6-smoke --inbox <entrega>`; cada arquivo é marcado como `AUTOMATED_TECHNICAL_SMOKE_TEST_ONLY` e não representa seleção editorial humana. O comando também inspeciona IDs, timestamps e bloqueios contra o ZIP original, sem usar mídia. Continue usando `output/scripts/R6_REVIEW_*.json` exclusivamente para roteiros selecionados de forma explícita na GUI ou CLI.

## Auditoria de mídia R6 (sem arquivos novos)

O comando `r6-media-audit --inbox <pasta-da-entrega>` é **somente leitura**. Ele encontra e calcula o SHA256 de arquivos locais nos diretórios conhecidos, sem criar relatórios salvos, sem importar mídia nem marcar cortes como aprovados. Toda trilha `output/r6_smoke/` continua para testes técnicos de seleção; `output/scripts/` segue reservado a roteiros editoriais explicitamente escolhidos.
