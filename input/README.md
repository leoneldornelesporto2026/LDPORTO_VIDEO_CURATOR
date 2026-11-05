# INPUT — Recebimento local do Analyzer

O Curator busca ZIPs reais em `input/analyzer/<video_id>/<run_id>/` e pacotes editoriais em `input/curadorias/`. **Esses ZIPs permanecem locais, não entram no Git.**

A pasta `input/scripts/` é reservada para **roteiros editoriais em JSON/Markdown/CSV/SRT/ASS** que se queira compartilhar. Pacotes do Analyzer não são automaticamente scripts executáveis do Curator: primeiro é necessária a segunda curadoria.

O seletor `VÍDEOS JÁ PROCESSADOS` lê arquivos existentes em `input/` mesmo quando são ignorados pelo Git.

Novos vídeos baixados ficam em `input/videos/<youtube_id>/<package_sha>/<tentativa>/source.mp4`. A pasta inteira `input/videos/` é ignorada pelo Git. Vídeos antigos podem permanecer em Vídeos do Windows ou em `output/projects/`; eles são reaproveitados sem migração quando a integridade for comprovada.
