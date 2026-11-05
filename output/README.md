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
