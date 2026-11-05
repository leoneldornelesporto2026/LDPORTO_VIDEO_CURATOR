# INPUT — Recebimento local do Analyzer

O Curator busca ZIPs reais em `input/analyzer/<video_id>/<run_id>/` e pacotes editoriais em `input/curadorias/`. **Esses ZIPs permanecem locais, não entram no Git.**

A pasta `input/scripts/` é reservada para **roteiros editoriais em JSON/Markdown/CSV/SRT/ASS** que se queira compartilhar. Pacotes do Analyzer não são automaticamente scripts executáveis do Curator: primeiro é necessária a segunda curadoria.

O seletor `VÍDEOS JÁ PROCESSADOS` lê arquivos existentes em `input/` mesmo quando são ignorados pelo Git.

Novos vídeos baixados ficam em `input/videos/<youtube_id>/<package_sha>/<tentativa>/source.mp4`. A pasta inteira `input/videos/` é ignorada pelo Git. Vídeos antigos podem permanecer em Vídeos do Windows ou em `output/projects/`; eles são reaproveitados sem migração quando a integridade for comprovada.

## Novo índice de evidências do Analyzer

Quando o Analyzer entrega o ZIP validado em `input/analyzer/<video_id>/<run_id>/`, também pode incluir `VIDEO_EVIDENCE_INDEX.json`. Esse índice lista **todos os arquivos efetivamente presentes no ZIP**, categoria, tamanho, SHA256 e lacunas relevantes. O inspetor `python -m ldporto_studio.analyzer_inbox --path <diretorio>` confere ZIP, recibo e índice por hash. O formato anterior sem índice permanece legível para entregas já realizadas.

O ZIP e o índice são **insumos de revisão**, não um pacote editorial R57 aprovado. A mídia fica separada em `input/videos/` e é ignorada pelo Git.

## Seleção R6 no Studio

Recebido um ZIP íntegro com recibo, selecione seu show pelo catálogo e clique **ABRIR / SELECIONAR CORTES**. O editor lê apenas os candidatos e evidências presentes, sem interpretar R6 como execução R57. O roteiro resultante é exportado em `output/scripts/`, não dentro do ZIP de origem. Para exportar pelo PowerShell: `python -m ldporto_studio r6-review --inbox ".\input\analyzer\<video_id>\<run_id>"`.
