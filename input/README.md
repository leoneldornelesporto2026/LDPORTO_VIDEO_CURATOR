# INPUT — Recebimento local do Analyzer

O Curator busca ZIPs reais em \`input/analyzer/<video_id>/<run_id>/\` e pacotes editoriais em \`input/curadorias/\`. **Esses ZIPs permanecem locais, não entram no Git.**

A pasta \`input/scripts/\` é reservada para **roteiros editoriais em JSON/Markdown/CSV/SRT/ASS** que se queira compartilhar. Pacotes do Analyzer não são automaticamente scripts executáveis do Curator: primeiro é necessária a segunda curadoria.

O seletor \`VÍDEOS JÁ PROCESSADOS\` lê arquivos existentes em \`input/\` mesmo quando são ignorados pelo Git.

O vídeo baixado do YouTube fica na pasta **Vídeos do Windows** (\`Videos/LDPORTO_VIDEO_CURATOR/\`), fora do repositório.
