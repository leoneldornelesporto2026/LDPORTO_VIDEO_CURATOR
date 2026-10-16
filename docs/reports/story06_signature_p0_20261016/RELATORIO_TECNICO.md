# Story 6 — assinatura corrigida e retomada concluída

Execução real em 16/10/2026, projeto `zd_wjssZ7mc`. O mesmo fluxo chamado pelo botão **RENDERIZAR TODOS** chegou ao Story **16/16**, com **16 prévias**, **0 bloqueados** e **0 finais de Stories aprovados**. Os **8 Reels concluídos** da revisão `6a1b69bda19d4103a932d9223ceb9c81` foram revalidados por SHA256 e preservados.

## Causa comprovada

A condição que emitia `Assinatura/estado da prévia recuperada não confere` estava em `_verified_recovered_preview`, em `ldporto_curator/combined_batch.py`. Das cinco condições agrupadas naquela mensagem, falhava somente:

```python
review['plan_signature'] != saved.signature(child)
```

`derive_unpreviewed_story` renderizava com `parent.cfg`, mas não persistia essa configuração. O verificador reabria `SeriesProject(directory, log=...)`, sem `cfg`. O construtor só restaurava configurações de `caption_revision`; a recuperação independente tem `story06_recovery`, portanto `saved.cfg` virava `{}`. `episode_signature` inclui o campo `settings` inteiro na assinatura. MP4, recibo, estado técnico e ausência de aprovação humana estavam coerentes.

| Identidade | SHA256 |
| --- | --- |
| Episódio original, assinatura calculada sem prévia própria | `bc3a8c2aa44352c79c48fc56e69d89de2744578bd984aca8a77ed4d7bd9d85b4` |
| Recuperação: `preview.plan_hash` e `review.plan_signature` | `9868ff1cb8711f21e100fada9adf34b8d32776f5747a21bd3783386728705f8f` |
| Recuperação reaberta incorretamente com `settings={}` | `3d683e23a8d77f2fafd1efaad5f58cf0211db72ee4eee3526ea4c2469be0282e` |
| Recuperação com o contexto exato da interface restaurado | `9868ff1cb8711f21e100fada9adf34b8d32776f5747a21bd3783386728705f8f` |

A identidade do episódio original é somente uma comparação calculada: ele não tinha uma prévia aprovada a ser herdada. A recuperação tem identidade independente legítima, com câmera e evidência suplementar documentadas.

Também foi comprovado por que simplesmente usar `config.yaml` ou o snapshot dos Reels não resolveria todos os casos: o contexto da interface inclui `source_media.path`, escrito com barras `/`. O snapshot dos Reels serializa `camera.min_zoom` como `1` e `question_focus_lookahead_seconds` como `9`, enquanto o YAML carrega `1.0` e `9.0`. Esses valores são numericamente iguais, mas possuem JSON e assinaturas diferentes. Nenhum hash histórico foi editado ou normalizado para contornar isso.

O fingerprint do renderizador era e continua sendo `93dee24827dae9c710dc7d5fc1e0305b0de8ca7277b4ebf92c7abcf9f9da20d6`. O motor de câmera não participou desta falha.

Evidência anterior às edições de código: [DIAGNOSTICO_SOMENTE_LEITURA.json](DIAGNOSTICO_SOMENTE_LEITURA.json). Simulação real após o patch: [SIMULACAO_FLUXO_NORMAL.json](SIMULACAO_FLUXO_NORMAL.json).

## Patch sobre os arquivos atuais

As alterações locais que já existiam foram copiadas antes das edições e mantidas. O patch desta tarefa, separado dessas alterações, está em [PATCH_P0_SOBRE_ESTADO_ATUAL.diff](PATCH_P0_SOBRE_ESTADO_ATUAL.diff).

| Arquivo | Correção |
| --- | --- |
| `ldporto_curator/combined_batch.py` | Restaura somente configurações que reproduzem exatamente a assinatura; valida proveniência, evidência, timeline, assets e MP4; separa integridade e aprovação; seleciona recuperações válidas preservando tentativas antigas; registra bloqueio local sem impedir partes independentes; publica checkpoints/manifests sem sobrescrever versões históricas. |
| `scripts/REPARAR_STORY06_SEM_QWEN.py` | Novas recuperações persistem `story06_recovery.render_settings` e seu SHA256, mantendo os tipos JSON originais. |
| `ldporto_curator/series_review.py` | A abertura da recuperação na GUI usa o mesmo verificador e restaura a configuração exata, preservando callbacks e a confirmação humana para aprovar. |
| `scripts/RETOMAR_STORIES_RECUPERADOS.py` | Reconstitui o contexto da mídia selecionada e informa o caminho efetivo do manifesto, inclusive quando versionado. |
| `ldporto_curator/gui.py` | Mostra quantidade de partes bloqueadas e caminho efetivo do manifesto retornado pelo fluxo normal. |

`series_workflow.py`, `episode_approval.py`, renderizador, presets de legenda, motor de câmera e alterações anteriores de `final_camera.py`/`REVISAR_CAMERA_SEM_QWEN.py` permanecem byte a byte iguais ao snapshot inicial deste P0. Nenhuma curadoria, chamada Qwen, transcrição, diarização ou nova análise do Analyzer foi executada.

## Contrato de integridade e aprovação

A revisão recuperada só é aceita quando confere com o projeto pai, ID do episódio, plano de origem, SHA256 da mídia e janelas editoriais. Os snapshots do pai são revalidados. As quatro fontes lexicais e seu manifesto são rehashados pela validação existente do suplemento; os registros completos de palavras e seus timestamps são comparados à evidência esperada. A câmera persistida e o asset renderizado precisam coincidir.

O recibo, a assinatura do episódio, o MP4 e todos os assets são conferidos. ASS e SRT são reconstruídos em diretório temporário a partir da timeline canônica e comparados por SHA256, sem alterar os arquivos existentes. A validação real adicional conferiu mídia, áudio, duração e dimensões dos 16 Stories.

| Condição | Estado registrado | Consequência |
| --- | --- | --- |
| Recuperação tecnicamente íntegra | `RECOVERED_PREVIEW_VALIDATED` | Prévia reutilizável. |
| Sem aprovação humana da revisão exata | `HUMAN_REVIEW_REQUIRED`, `ready_for_final_render=false` | Continua a gerar outras prévias; nenhum final deste episódio. |
| Aprovação humana válida do mesmo filho e assinatura | `PREVIEW_APPROVED`, `ready_for_final_render=true` | Pode renderizar final conforme o gate já existente. |
| Integridade/lexical insuficiente e recuperação nova inviável | `RECOVERY_BLOCKED`, `technical_state=BLOCKED` | Preserva tentativa, registra motivo e continua episódios independentes. |

Aprovação dos Reels e aprovação dos enquadramentos de demonstração não foram transferidas ao Story 6. Nenhum `approved=false` virou `true`. A autorização de publicação permanece falsa.

## Execução real e resultado

O projeto pai é `output/projects/zd_wjssZ7mc/stories_30af3ad6a05923e2`. A recuperação reutilizada é `story06_caption_recovered_8bb69282f0f4`, sem criar outra revisão e sem reencodar o Story 6.

O log [RETOMADA_REAL.log](RETOMADA_REAL.log) registra:

- 11:28:35 UTC: Reels revalidados e preservados.
- Stories 1–5: MP4 existente revalidado e preservado.
- 11:28:39 UTC: Story 6 íntegro, prévia reutilizada e revisão audiovisual humana pendente.
- 11:28:39 UTC em diante: avanço real pelos Stories 7–16, com renderização apenas dessas dez prévias.
- 11:29:48 UTC: manifesto completo, 16 partes, 16 prévias, 0 finais aprovados, 0 bloqueados.

As séries mantêm a ordem **S01: 3 partes; S02: 5 partes; S03: 8 partes**. Títulos, limites de origem, ordem, presets, textos e evidência original foram preservados. O Story 6 mantém os **21 eventos e 102 word IDs**, incluindo as 12 palavras recuperadas. Todos os 16 Stories passaram nas verificações de karaokê amarelo → branco, área segura e máximo de duas linhas. A câmera conservadora da recuperação continua pendente de revisão audiovisual humana.

Manifesto efetivo: [LOTE_STORIES_EM_ORDEM.json](../../../output/projects/zd_wjssZ7mc/stories_30af3ad6a05923e2/LOTE_STORIES_EM_ORDEM.json). Cópia do resultado: [RESULTADO_RETOMADA_REAL.json](RESULTADO_RETOMADA_REAL.json). Detalhes das 24 mídias atuais, assets e estados: [ACEITE_REAL_16_STORIES.json](ACEITE_REAL_16_STORIES.json).

A segunda execução completa pela função usada na GUI produziu **zero arquivos novos e zero arquivos alterados** em `output`, `.cache`, `source_cache` e backups: [IDEMPOTENCIA_REAL.json](IDEMPOTENCIA_REAL.json). A execução adicional pelo CLI corrigido também reutilizou tudo: [CLI_RETOMADA_IDEMPOTENTE.log](CLI_RETOMADA_IDEMPOTENTE.log). A conferência final de 1.467 arquivos locais após o CLI não encontrou alteração ou ausência: [VERIFICACAO_FINAL_APOS_CLI.json](VERIFICACAO_FINAL_APOS_CLI.json).

## Testes

**60 testes passaram**, com escrita apenas em diretórios temporários exclusivos e cache do pytest desativado. Resultado final: [TESTES_COMPLETOS.xml](TESTES_COMPLETOS.xml).

As regressões cobrem os 12 cenários solicitados: recuperação válida, adulteração real, identidade nova legítima, pendência humana, aprovação da revisão exata, coexistência, interrupção no Story 6, repetição idempotente, insuficiência lexical, preservação dos cinco Stories e oito Reels, avanço até 16 e bloqueio do final sem aprovação humana. Cobrem também configuração congelada adulterada, ID de projeto divergente, manifesto interrompido, contexto legado e abertura/aprovação pela GUI.

Os testes automatizados usam mídia pequena fictícia e simulam o encoder quando apropriado; a aceitação em produção acima executou FFmpeg real para as dez prévias faltantes e validou as 24 mídias atuais por hash. O comando de referência está em [ROLLBACK_E_BACKUP.md](ROLLBACK_E_BACKUP.md).

## Inventário e proteção de output

O snapshot inicial deste P0 tem **1.158 arquivos protegidos**, incluindo a mídia externa, e **2.091.898.220 bytes**. Foi criado antes das edições. Os inventários históricos de outras sessões permanecem como histórico; a comparação desta tarefa usa o estado realmente encontrado em 16/10.

Após a retomada, **1.156 desses arquivos estão byte a byte idênticos e nenhum desapareceu**. Os únicos dois arquivos correntes atualizados são:

| Arquivo | Antes | Depois |
| --- | --- | --- |
| `series_index.json` do projeto pai | `aa429a50ac14ffaffafe60490b06195d7fb74f1bbc4c37e46baf251d2ba7eb01` | `0e7604341ec57cd244736b6ea5b3757bc4dc8568df6a4d44ce45b8f7b7fd878b` |
| `SERIES_PLAYLIST_ORDER.m3u` do projeto pai | `305944b0e48b81fe669877d58466eb76c24dce0354862313f1bec3b33d547fc5` | `4107f8f6bd426195620958fbd52994eedffa659e2d060a041da73d3f6cccdb98` |

O índice anterior existe integralmente em `revisions/aa429a50ac14ffaf.json` e no backup desta tarefa. A playlist anterior também está no backup. São atualizações de registro das dez prévias novas; todos os MP4s, ASS/SRT, projetos recuperados, revisões e aprovações preexistentes foram preservados. Foram adicionados 310 arquivos de renders, assets, snapshots, checkpoints e manifestos.

| Árvore local ao final | Arquivos | Bytes |
| --- | ---: | ---: |
| `output` | 964 | 710.423.936 |
| `.cache` | 502 | 94.732.892 |
| `source_cache` | 1 | 1.200.651.212 |

As chamadas **somente leitura** de `cleanup_preview` retornaram **zero arquivos removíveis e zero bytes liberáveis** nas três árvores. Foram identificados 169 grupos de bytes duplicados e mantidos integralmente: [DUPLICATAS_PRESERVADAS.json](DUPLICATAS_PRESERVADAS.json). A tentativa antiga incompleta do Story 6, em `cc73a6c2fd0046b2/preview`, também foi preservada. Nenhuma limpeza executiva, movimentação, reorganização, commit ou push foi realizado.

A mídia original externa continua com SHA256 `b2958122415980a8afff4f77c23ead3c31c00345e5df0ab460995eb731efb00f`. A cópia diferente em `source_cache` também foi preservada. Proteção e hashes completos: [PROTECTED_BEFORE.json](PROTECTED_BEFORE.json), [PROTECTED_AFTER.json](PROTECTED_AFTER.json), [HASHES_ANTES_DEPOIS.json](HASHES_ANTES_DEPOIS.json), [CODE_BEFORE.json](CODE_BEFORE.json) e [CODE_AFTER.json](CODE_AFTER.json).

## Revisão humana e backup

**As 16 prévias continuam pendentes de aprovação humana.** A lista nominal e a orientação para abrir a revisão exata do Story 6 estão em [APROVACOES_PENDENTES.md](APROVACOES_PENDENTES.md).

Backup dos arquivos de código atuais antes do patch: `backup_code/`. Backup dos metadados e assets textuais protegidos: `backup_state/`. Procedimento de rollback sem exclusão de resultados: [ROLLBACK_E_BACKUP.md](ROLLBACK_E_BACKUP.md).
