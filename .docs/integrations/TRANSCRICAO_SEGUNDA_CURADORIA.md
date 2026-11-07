# Segunda curadoria: transcrição original, conferência e render com legendas

O Analyzer escuta o vídeo completo e transcreve. O pacote R6 entregue em input/analyzer/ contém os arquivos textuais originais disponíveis, a origem e os SHA256. O Analyzer não aprova ASR nem ativa legendas finais.

O Curator recebe a análise original e cria rascunhos SRT/ASS com tempos relativos a cada Reel/Story, sem alterar texto da fonte. A segunda curadoria precisa conferir o áudio, palavras, termos técnicos, idioma, pontuação, duração, contexto, alinhamento e quebras. Para apoiar isso, o comando `captions-second-check` mostra cada fala original e aponta inconsistências estruturais de SRT/ASS, tempos sobrepostos e velocidade de leitura.

O relatório é **checagem estrutural**, não reconhecimento de voz independente, prova de conteúdo, correção de ASR ou aprovação humana. O áudio real precisa ser ouvido. O operador corrige SRT/ASS quando necessário, importa ASS revisada, volta a conferir a fala, marca na GUI as opções 'Conferi transcrição e áudio' e 'Incluir karaokê ASS no vídeo' somente após revisão. Mudar legenda ou configurações invalida aprovações anteriores; gere outra prévia. ASR não conferido permanece oculto.

CLI: `python -m ldporto_studio captions-second-check --workdir <output/projects/PROJETO> --id REEL_01`

Para salvar relatório local: acrescente `--save`. O arquivo vai para `exports/caption_second_pass/REEL_01/SECOND_PASS_*.json`, com hashes e marcações `captions_verified=false`, `human_approved=false` e sem alteração do projeto. A GUI também dispõe de '2ª CHECAGEM DE LEGENDAS (SRT/ASS)'.

Git: o Analyzer possui `scripts/dev/export_r6_git_review.py` para exportar os **textos do ZIP canônico R6** para `docs/analyzer_runs/<video>/<run>/`, sob revisão explícita. Inclui SRT/JSONL, catálogo, câmera e demais textos disponíveis. Não versiona vídeos, imagens, modelos ou dados temporários. O script nunca realiza Git push automático; arquivos precisam de conferência de confidencialidade e direitos. Veja a documentação no repositório Analyzer em `.docs/integrations/ANALYZER_R6_GIT_EVIDENCE.md`.

Estes controles são válidos somente após testes Windows no ambiente do operador. Não promover para main/release antes da regressão da câmera e das legendas.