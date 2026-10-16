# Entrega P0 — legendas dos Stories V5.2.2

15/10/2026 — America/Sao_Paulo.

O código de produção foi corrigido e a Parte 1 foi renderizada em uma revisão derivada. A exibição escolhida é palavra por palavra, sem antecipação. ASS e SRT usam os mesmos 71 eventos e os mesmos IDs originais; nenhuma palavra foi reescrita, perdida ou repetida. O vídeo mantém 26,22 segundos.

Abra [REVISAO.html](REVISAO.html) para assistir e comparar os dez instantes solicitados. A [prévia MP4](story_parte_1/PREVIEW_540x960.mp4), o [ASS](story_parte_1/CAPTIONS.ass), o [SRT](story_parte_1/CAPTIONS.srt), o [SUBTITLE_SYNC revisado](story_parte_1/SUBTITLE_SYNC.json) e o [relatório por evento](story_parte_1/EVENT_SYNC_REPORT.json) estão nesta pasta. A exportação [1080×1920](story_parte_1/resolution_1080x1920/) reutiliza a timeline da prévia, sem encode final.

## Causa e solução

O motor antigo tratava destaque desativado como motivo para ignorar os tempos das palavras. Também gerava o SRT por segmentos, independentemente do ASS, e permitia mais de duas linhas no fallback visual. O novo motor separa apresentação e alinhamento, mede a fonte local, normaliza sua escala para o libass, limita o layout e valida o conteúdo das timelines congeladas. O [relatório técnico](validation/CAUSA_RAIZ_LEGENDAS_STORIES_P0.md) identifica arquivos, funções e caminhos de produção afetados.

Registros ASR fragmentados, como `8` + `.500`, `1` + `.112` e `terça` + `-feira`, agora conservam seus próprios IDs, substrings e intervalos, sem presumir um registro por espaço. Doze palavras ausentes no pacote importado foram recuperadas dos arquivos originais já existentes do Analyzer, com quatro hashes, identidade SHA256 da fonte e correspondência ao cache ASR conferidos. Somente a evidência da revisão derivada recebeu esses registros; a transcrição e os arquivos históricos permanecem intactos. A procedência está em [ALL_EPISODES_VALIDATION.json](ALL_EPISODES_VALIDATION.json) e no [manifesto de recuperação](validation/WORD_EVIDENCE_SEG00163.json).

## Validação executada

| Verificação | Resultado |
| --- | --- |
| Suíte completa | **554 passaram, 2 ignorados, 0 falhas**, em 57,94 s |
| Parte 1 | 71 eventos, 71 IDs únicos em ordem, tempos originais preservados |
| ASS/SRT | Texto e tempos equivalentes; arredondamento somente no formato final |
| Layout da Parte 1 | Uma linha por evento, dentro da área segura |
| Todas as partes | 16 episódios, 1.246 registros de palavras, sem perda/duplicação |
| Outros 15 episódios | ASS/SRT/JSON preparados; todos com alinhamento por palavras e layout permitido |
| Render em lote / finais / novas aprovações | Nenhum |
| Arquivos protegidos iniciais | **1.188/1.188 com SHA256 e tamanho idênticos** |
| Sete arquivos com alterações locais anteriores | Bytes preservados |
| Inicialização final | 103 compilações, 54 imports, CLI e interface oculta passaram |
| Organização | Nenhum original movido ou removido; 0 bytes recuperados |

Os dois testes ignorados dependem de arquivos de um pacote legado que já estavam ausentes antes do trabalho. A verificação atual dos 1.188 arquivos existentes foi executada independentemente e passou. O [JUnit completo](validation/pytest_final_p0_v2.xml), a [integridade final](validation/protected_hashes_final_v2.json), a [validação da inicialização](STARTUP_VALIDATION.json) e o [inventário inicial](validation/inventory_before.json) estão incluídos.

Os dez pares de frames foram extraídos em 0,5; 1,5; 3; 5,5; 8,5; 10; 14,5; 19; 23 e 25,5 segundos e inspecionados visualmente. As palavras mudam entre amostras, permanecem dentro do quadro e não cobrem o rosto, o conteúdo central nem o título. Os títulos de cinco segundos, a câmera e as cinco capas de cada episódio foram preservados por conteúdo/hash.

A correlação do áudio da prévia com o trecho original foi **0,9998346**, com defasagem global medida de **0 ms** a 8 kHz. Essa medida verifica continuidade e alinhamento global do áudio; não confirma a fala de cada palavra nem a precisão individual dos timestamps ASR. O [áudio para conferência](story_parte_1/AUDIO_PARA_REVISAO.wav) e as [limitações da medição](story_parte_1/AUDIO_REVIEW.json) estão disponíveis. O estado continua **NEEDS_HUMAN_AUDIO_REVIEW**, sem aprovação/publicação automática.

## Preservação e uso

O original usado foi `../LDPORTO_VIDEO_ANALYZER/input/youtube/zd_wjssZ7mc/zd_wjssZ7mc.mp4`, com SHA256 `b2958122415980a8afff4f77c23ead3c31c00345e5df0ab460995eb731efb00f`. A cópia divergente de `source_cache` foi preservada e não foi usada. Não houve download, nova curadoria, Qwen, reprocessamento do Analyzer, limpeza de caches, commit ou push.

Os oito Reels e o projeto histórico dos Stories continuam nos diretórios originais. A revisão utilizável fica em `output/projects/zd_wjssZ7mc/captions_p0_20261015_v2/series_index.json`. Na interface, use **Retomar projeto** para abri-la e selecione a mídia original verificada. As três séries mantêm 3, 5 e 8 partes, na ordem original. O diretório anterior `captions_p0_20261015` foi preservado como evidência de desenvolvimento e está substituído pela revisão `_v2`.

O ZIP `docs/reports/captions_p0_package_20261015/UPDATE_LEGENDAS_STORIES_P0.zip` inclui código, testes, evidências e o instalador PowerShell. O arquivo `.zip.sha256` ao lado permite conferir o pacote. O instalador valida hashes antes de copiar, preserva alterações locais divergentes, cria backup e permite rollback com conferência dos arquivos instalados e restaurados. Seus testes incluem adulteração, caminhos/junctions, falha parcial e recusa de rollback após edição local.

Feche o Curator, extraia o pacote em uma pasta separada e execute o instalador com `-TargetRoot` apontando para a instalação. `-VerifyOnly` faz a conferência sem alterações. O caminho do manifesto de rollback é informado ao concluir a instalação. Nesta workspace o código já está atualizado; não é necessário reinstalá-lo.
