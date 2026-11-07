# R6 para R57: prefill auditável de assets para revisão

O comando r6-assets-prefill consolida rascunhos já extraídos em uma pasta isolada para preparar o checklist R57. Não executa FFmpeg, ASR, IA, downloads, importação R57, aprovação ou publicação.

## Pré-requisitos
- Pacote R6 íntegro no Curator, roteiro exportado após seleção humana de Reels e proposta de Stories da mesma origem.
- Pasta COVERS_R6_DRAFT_* gerada do vídeo SHA256 exato com COVER_DRAFT_MANIFEST.json.
- Pasta CAPTIONS_R6_DRAFT_* opcional, gerada do SRT original com CAPTION_DRAFT_MANIFEST.json.

## Inspeção somente leitura
python -m ldporto_studio r6-assets-prefill --inbox <inbox> --draft <R6_REVIEW.json> --story-proposal <R6_STORY_PROPOSAL.json> --covers-dir <COVERS_R6_DRAFT> --captions-dir <CAPTIONS_R6_DRAFT>

Sem --captions-dir, legendas permanecem nulas e são relatadas como pendentes. Por padrão nenhum arquivo é criado.

## Salvar staging
Acrescentar --save. A saída fica em output/r6_bridge/<source_sha_prefix>/ASSETS_R6_STAGING_<hash>/, com R6_ASSET_STAGING_MANIFEST.json, R6_ASSET_BINDINGS_DRAFT.json e os arquivos existentes organizados por reels/<id>/ e stories/<id>/.

Cada arquivo copiado tem SHA256 e formato conferidos. Campos faltantes não são completados com placeholders. Staging alterado nunca é sobrescrito silenciosamente. O botão PREENCHER ASSETS COM RASCUNHOS disponibiliza o mesmo fluxo na GUI.

## Gate para o Studio
Após revisão humana, valide R6_ASSET_BINDINGS_DRAFT.json usando r6-assets com --bindings <arquivo> e --assets-root <staging>. Essa auditoria verifica estrutura e integridade, não alinhamento de áudio, conteúdo de vídeo, direitos ou aprovação.
Somente com todos os assets existentes, r6-r57-preview-package permite um ZIP de prévias mediante --save --confirm-preview-only. ZIP de prévia não equivale a aprovação final; prévias e direitos ainda precisam ser revisados. Nenhum render, merge ou publicação é feito aqui.