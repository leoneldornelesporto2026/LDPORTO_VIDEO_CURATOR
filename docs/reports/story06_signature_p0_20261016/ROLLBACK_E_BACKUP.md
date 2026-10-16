# Backup e rollback do P0 Story 6

Nenhum rollback foi executado. Estes arquivos permitem revisar ou desfazer somente o patch desta tarefa, preservando as modificações locais que já existiam antes dele.

## Conteúdo preservado

- `backup_code/`: 151 arquivos de código, scripts, testes e configuração copiados antes das edições. `CODE_BEFORE.json` registra tamanho e SHA256 de cada um.
- `backup_state/`: cópias anteriores dos JSON, ASS, SRT, playlists e demais arquivos textuais encontrados nas árvores protegidas. Não é uma cópia integral de todos os MP4s.
- `PROTECTED_BEFORE.json`: inventário com SHA256 dos 1.158 arquivos protegidos, incluindo mídia externa. Os próprios MP4s e demais binários originais continuam nos seus caminhos; nenhum foi sobrescrito ou removido.
- `git_status.txt`, `git_diff.txt`, `git_head.txt`: estado Git e alterações locais anteriores.
- `PATCH_P0_SOBRE_ESTADO_ATUAL.diff`: somente a diferença desta tarefa sobre o backup inicial.

O índice inicial do projeto pai também foi arquivado automaticamente em `output/projects/zd_wjssZ7mc/stories_30af3ad6a05923e2/revisions/aa429a50ac14ffaf.json`. Sua cópia exata e a playlist inicial estão em `backup_state/output/projects/zd_wjssZ7mc/stories_30af3ad6a05923e2/`.

## Procedimento de rollback de código

1. Fechar o Curator e confirmar que não há render em execução.
2. Comparar os cinco arquivos abaixo com `CODE_AFTER.json`. Se houver edições posteriores, conciliá-las antes de restaurar qualquer arquivo.
3. Criar outro backup dos arquivos correntes em pasta inédita.
4. Restaurar somente estes arquivos a partir dos caminhos equivalentes em `backup_code/`:
   - `ldporto_curator/combined_batch.py`
   - `ldporto_curator/gui.py`
   - `ldporto_curator/series_review.py`
   - `scripts/REPARAR_STORY06_SEM_QWEN.py`
   - `scripts/RETOMAR_STORIES_RECUPERADOS.py`
5. Conferir os hashes restaurados contra `CODE_BEFORE.json`.

Não executar `git reset`, `git clean`, limpeza de output ou restauração em massa do estado. Os dois testes novos e os relatórios podem permanecer como histórico. O backup preserva inclusive as modificações anteriores em `combined_batch.py`; voltar à versão do Git descartaria essas modificações.

Restaurar o código não exige remover prévias novas, recuperação, manifests, checkpoints ou snapshots. Uma restauração do índice corrente dos Stories faria a interface voltar a um estado anterior e deve ser uma decisão separada, com conciliação das dez novas prévias. O estado anterior já está disponível no histórico, sem necessidade de substituir o índice atual.

## Validação isolada

Com uma pasta temporária **inédita** para cada execução, os testes finais foram:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest `
  tests/test_story06_signature_resume_p0.py `
  tests/test_story06_review_context_p0.py `
  tests/test_story06_recovery_p0.py `
  tests/test_story06_camera_revision_p0.py `
  tests/test_integracao_camera_stories_p0.py `
  tests/test_p0_gui.py `
  tests/test_v52_visual_callbacks.py `
  -q -p no:cacheprovider --basetemp "$env:TEMP\ldporto_story06_p0_acceptance_20261016"
```

Resultado registrado: **60 passed in 10.99s**. Para repetir, mudar `--basetemp` para um novo nome; o pytest pode limpar o diretório que lhe é passado. Nunca apontar esse argumento para output, caches, fontes ou backups.

O programa precisa ser reaberto para carregar o código Python atualizado. A abertura da revisão recuperada faz validação somente de leitura; a aprovação continua sendo uma ação humana explícita após assistir ao MP4.
