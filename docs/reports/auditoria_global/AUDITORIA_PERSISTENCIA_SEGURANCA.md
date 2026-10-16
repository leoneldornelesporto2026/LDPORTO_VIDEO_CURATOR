# Auditoria de persistência e segurança — 16/10/2026

Escopo: contratos de estado, arquivos, hashes, aprovações, locks, fontes, render, recuperação, histórico e scripts de escrita. A inspeção foi somente leitura de produção; a evidência do incidente de output e as ações anteriores à suspensão estão documentadas separadamente em [P0_OUTPUT_DESLOCADO_AUDITORIA.md](P0_OUTPUT_DESLOCADO_AUDITORIA.md). Não atribuir o estado vazio atual a uma função sem evidência de execução.

## Contratos existentes e pontos de escrita

| Área | Funções e linhas | Contrato observado |
| --- | --- | --- |
| Pipeline persistido | `persisted_plan.py:125`, `:203`, `:235`, `:337` | `render_settings` exclui localização; fingerprints prendem fonte, decisões e efeitos. PlanStore mantém inputs/snapshot imutáveis e ponteiro corrente. |
| Publicação de estado | `persisted_plan.py:235`, `:460`, `:467` | JSON temporário UUID exclusivo, flush/fsync e replace; snapshots de estados por versão; CAS verifica revisão e `state_version`. |
| Locks de projeto | `persisted_plan.py:277`, `:286`, `:330` | Exclusão mútua de estado/operação; PID vivo ou proprietário desconhecido não é deslocado. Recuperação de lock exige token inalterado e PID morto. |
| Pipeline Reels | `pipeline.py:84`, `:112`, `:134`, `:181`, `:334`, `:385`, `:424`, `:442` | Leitura pode recuperar lote interrompido ou converter legado, sob lock. Preview/aprovação/lote reutilizam inputs congelados. Caminhos atuais de renders são construídos em `:404` e `:487`. |
| Aprovação Reels | `approval.py:33`, `:43`; `pipeline.py:356` | MP4 e sidecar têm SHA256; aprovação fica ligada a revisão, fonte e assinatura. Caminhos persistidos são absolutos. Flag isolada não autoriza o pipeline. |
| Aprovação Stories | `episode_approval.py:21`, `:28`, `:42`, `:61`, `:75`, `:89` | Assinatura inclui todo cfg e campos editoriais; assets do recibo devem resolver dentro da pasta de revisão. Aprovação exige ação humana explícita. |
| Projetos Stories | `series_workflow.py:308`, `:473`, `:501`, `:642`, `:737`, `:744`, `:749`, `:907` | Índice e evidências em projeto; revisões e assets congelados por hash; render com tentativa exclusiva e publicação sem substituir. Índice anterior é guardado por SHA256. |
| Histórico editorial | `editing_history.py:40`, `:58`, `:92` | Snapshots por conteúdo; undo/redo preserva histórico e gira nonce das partes alteradas. Não herda aprovação da geração antiga. |
| Revisão de câmera | `camera_revision.py:19`, `camera_metadata.py:33`, `:134`, `:165` | Destino novo; cópias verificadas; proveniência liga arquivo visual, plano original, fonte e intervalo. Metadados visuais não são uma aprovação. |
| Story 6 | `combined_batch.py:147`; `scripts/REPARAR_STORY06_SEM_QWEN.py:99`; `series_review.py:20` | Verifica fonte, complemento lexical, câmera, recibo, timeline e ASS/SRT. Configuração pinned/legacy precisa reproduzir assinatura exata. GUI restaura esse contexto sem salvar o projeto. |
| Retomada combinada | `combined_batch.py:417`; `scripts/RETOMAR_STORIES_RECUPERADOS.py:75` | Reutiliza arquivos íntegros, distingue bloqueio, prévia e aprovação humana; manifesto e checkpoints preservam histórico. |
| Render Reels | `render.py:439`, `:452`, `:466`, `:475`, `:490` | Recibo exclusivo antes de assets; pending UUID; encode com `-n`; validação; hard link recusa colisão; tentativa interrompida é preservada. |
| Fontes | `source_video.py:10`, `:17`; `pipeline.py:219` | SHA256 prevalece sobre URL/nome. Download depende de opção explícita; cache existente não é apagado. A fonte do Analyzer não é migrada. |
| Limpeza | `storage.py:104`, `:134`, `:191`, `:220`; `storage_dialog.py:6` | Protege output, caches, originais, projetos, revisões, aprovações, evidências, backups e docs; só scratch registrado e verificado pode ser candidato. Execução exige confirmação. |
| Importação | `second_curation_import.py:13`, `:62`; `evidence_source.py:92` | ZIP tem limites, checksums, tipos e caminhos verificados; cache por hash; registry e derivados são gravados. Não apaga output. |
| Handoff | `full_handoff.py:109`, `:185`, `:288` | Exportação por assinatura, ZIP exclusivo e manifesto; redige caminhos privados. Pacote parcial é preservado e requer outro destino. |
| Geradores de assets | `thumbnails.py`, `thumbnail_presets.py`, `title_card.py`, `title_presets.py`, `subtitles.py`, `subtitle_presets.py`, `media_effects.py` | Criam frames/PNG/ASS/SRT e metadados no diretório fornecido. Alguns usam FFmpeg `-y`; a exclusividade precisa ser garantida pelo chamador. Não executar em pastas históricas arbitrárias. |
| Estado auxiliar | `gui.py:350`, `eta.py:75`, `feedback.py:16`, `utils.py:6`, `:12` | Sessão GUI tem replace temporário; ETA/feedback/JSON genérico usam escritas diretas. São contratos distintos dos commits CAS de PlanStore. |

O mapa geral de operações levantado pela sessão está em [OPERACOES_ARQUIVOS.json](OPERACOES_ARQUIVOS.json). Buscas por `delete`, `remove`, `move` e `replace` foram conciliadas com o contexto: exclusões de widgets/listas e substituições de strings não são operações de disco.

## Riscos demonstráveis e limites

| Prioridade | Evidência | Consequência e tratamento proposto |
| --- | --- | --- |
| P1, compatibilidade | `episode_approval.py:28–39` assina `settings=cfg` integralmente, sem canonicalização int/float. | Adicionar preferência de storage ao cfg de um Story legado pode invalidar sua assinatura. Preferências de armazenamento precisam ficar fora do cfg assinado ou usar o snapshot exato por revisão. Não renormalizar silenciosamente tipos ou grafia dos caminhos. |
| P1, compatibilidade | `episode_approval.py:21–25` e `pipeline.py:29–33` hasheiam módulos de render inteiros. | Editar `render.py`, `series_workflow.py`, módulos de legenda/título e outros da lista altera as assinaturas atuais. Infraestrutura de storage deve ser adicionada fora desses arquivos nesta fase. Não remover checks para aceitar fingerprints diferentes. |
| P1, concorrência | `SeriesProject.save`, `series_workflow.py:642–660`, usa `series_index.pending.json` fixo e não adquire lock/CAS. | Dois processos podem disputar o pending e publicar índices derivados de estados diferentes. A exclusividade do MP4 não protege o índice. Adicionar exclusão mútua no adaptador/orquestrador e testar writers concorrentes; não foi reproduzida perda real por esse mecanismo nesta auditoria. |
| P1, interrupção | `SeriesProject.save:652–660` grava evidências, manifests e playlist antes do replace do índice; `utils.write_json:12–14` faz escrita direta. | Uma interrupção pode deixar derivados ou JSON auxiliar parcial. O índice é o commit corrente, mas o conjunto não constitui uma transação durável única. Usar journal e geração de metadados com publicação transacional na nova camada. |
| P1, migração | `series_workflow.py:50–54`, `:795`, `:867–868`; `episode_approval.py:61–72`. | Trocar simplesmente caminhos relativos por externos quebra confinamento, finalização/canonical timeline e derivações. Um adaptador precisa cobrir leitura, finalização, revisão, exportação e GUI, preservando os verificadores existentes. |
| P1, publicação | `render.py:490`, `series_workflow.py:862`, `combined_batch.py:399` usam hard link. | Staging e destino final precisam estar no mesmo volume e suportar hard link. Nunca colocar staging no TEMP de outro volume para depois tentar esse commit. Arquivo pendente deve nascer ao lado do destino externo. |
| P2, retomada | `pipeline.py:442–519` inicia nova tentativa e percorre todos os clips; resultados parciais são registrados em `batch_history`. | O lote direto não é retomada por clip. O fluxo combinado evita lote concluído por SHA256; parcial requer política explícita de reutilização por identidade, sem nova aprovação automática. |
| P2, cache/importação | `second_curation_import.py:68–83`, `:129`; `utils.load_json:6–10`. | Reimportação regrava derivados e registry; erro de JSON pode virar default, indistinguível de ausência. Não é prova da causa do incidente. Reservar falha explícita para estado obrigatório e commit atômico para registry. |
| P2, locks interrompidos | `persisted_plan.py:277–327`. | Lock malformado falha fechado; proprietário desconhecido não é presumido morto. Manter diagnóstico/recuperação explícita, nunca apagar locks para forçar execução. |
| P2, source discovery | `source_video.py:25–30`. | Busca recursiva em ancestrais pode ser ampla; não apaga a fonte. Preferir índice SHA256 e referência explícita antes da busca legada. |

Os riscos de concorrência/interrupção acima são consequências verificáveis da ordem das operações; não constituem atribuição de um incidente já ocorrido. Nenhum teste destrutivo ou render foi executado nesta auditoria.

## Scripts, instalação e remoções reais

- `storage.execute_cleanup:240` remove somente arquivo individual revalidado. As árvores de dados são bloqueadas antes disso. Não foi chamada.
- `storage.media_lease:81`, `persisted_plan.py:248/302/318/322/327` e `combined_batch.py:405` removem temporários/locks próprios. Os pending MP4 são removidos em `render.py:491` e `series_workflow.py:863` depois da publicação por hard link. Isso não é exclusão recursiva de output.
- `camera_revision.py:121` renomeia o marcador de revisão incompleta após conclusão. Cópias de evidência e assets têm destino novo e verificação SHA256.
- `INSTALL_CAMERA_FINAL.ps1:28–46` valida escopo/caminhos e bloqueia árvores protegidas; `:58–80` publica por staging verificado; `:81–135` mantém journal de rollback. `Remove-Item:123` é remoção pontual de código novo no rollback, com hashes e escopo verificados.
- `INSTALL_CAPTIONS_P0.ps1:40–42` usa journal escrito diretamente, e `:136` copia código com `-Force`. Seu rollback só aceita `INSTALLED`; interrupção abrupta pode exigir recuperação manual. As remoções `:78/:148` são pontuais de código criado pela instalação. Não usar esse instalador histórico como motor de migração de mídia.
- `RECUPERAR_OUTPUT_LDPORTO.py` reconstrói propostas novas a partir de evidências verificadas; **não recupera vídeos ou aprovações apagados**. Recusa destino/snapshot existente e não deve substituir os payloads encontrados na Lixeira.
- `REPARAR_STORY06_SEM_QWEN.py`, `REVISAR_CAMERA_SEM_QWEN.py` e `NOVAS_PREVIAS_STORIES_CAMERA.py` criam revisões separadas. Scripts `validate_*`, `render_camera_demos_hd`, `capture_*` e `demo_*` podem gerar mídia pesada em reports/cache; nomes e diretórios devem ser inéditos. Não são rotinas de inicialização.
- `build_camera_update.py` e `build_caption_update.py` copiam payload/evidências e criam ZIPs; preservar pacotes anteriores. `verify_caption_protected_hashes.py` apenas lê protegidos e escreve seu relatório.
- BATs de abertura/diagnóstico/instalação inspecionados não contêm limpeza de output. O instalador BAT altera ambiente/dependências; isso é diferente de remover dados do projeto.

A busca no código ativo não encontrou `rmtree`, `Remove-Item -Recurse`, `rd /s`, `send2trash`, `SHFileOperation` ou `IFileOperation` para esvaziar output. A presença dos `$I/$R` demonstra reciclagem, mas não identifica quem chamou a operação nem qual versão de programa estava em execução.

## Integração externa preservando as assinaturas

Esta é uma proposta, não aplicada. Migração e novas cópias permanecem suspensas.

1. Resolver a pasta Vídeos por Known Folder do Windows, respeitando redirecionamentos; oferecer destino configurável. Guardar preferência de infraestrutura em arquivo separado do cfg editorial legado. O backup de preservação resolveu Vídeos por `Environment.GetFolderPath(SpecialFolder.MyVideos)`, sem hardcode do usuário.
2. Manter PlanStore, índices, estados, aprovações e revisões em output. Originais do Analyzer e mídia legada permanecem intactos. Cada nova mídia precisa de namespace com vídeo/revisão/episódio/assinatura/tentativa para impedir colisões.
3. Reels têm uma fronteira utilizável em `Pipeline._render_cfg` e nos locais `:404/:487`: o render aceita `out_dir` explícito e as localizações não fazem parte da projeção de settings de PlanStore. `pipeline.py`, helpers de storage e chamadores estão fora do fingerprint de pixels. Também é necessário rotear thumbnails e ampliar a verificação de pertencimento de `_verified_batch_artifacts:112`/`reel_batch_complete` para destinos cadastrados por hash, mantendo suporte ao legado.
4. Stories exigem adaptador explícito em módulo novo, fora da lista do renderer. Reutilizar os mesmos helpers de legenda, título, filtros, validação e aprovação, com cfg exato. `preview`/`final` são excluídos da assinatura editorial; suas referências podem ser tratadas como localização pelo adaptador. Entretanto o render original, `_inside_file`, frozen assets, derive/export e a GUI têm contratos de confinamento e precisam ser atendidos em conjunto. Apenas trocar `folder()` ou inserir symlink/junction não resolve esse contrato.
5. Não usar symlink/junction como mecanismo de migração: verificadores de câmera, storage, handoff e assets rejeitam links/reparse points. Não alterar globalmente `Path.resolve`, `relative_to` ou a função de hash para contornar a verificação.
6. O adapter novo deve armazenar os recibos/metadados autoritativos em output e um registro verificável de localização. Para mídia nova, staging deve ficar no volume do destino, ser publicado exclusivamente e ter tamanho/SHA256 registrados antes do commit de estado. Metadados precisam de journal e recuperação idempotente.
7. Antes de aceitar infraestrutura nova para uma revisão existente, provar a igualdade das assinaturas, dos inputs de filtros, das legendas e dos bytes preservados. Mudança real de pixels/engine exige nova revisão e revisão humana; nunca transportar aprovação antiga para uma identidade diferente.

O contrato mínimo de migração deve registrar origem, destino, tamanho, SHA256, geração, fase, dono da operação e estado do commit. Dry-run não escreve nas árvores de dados. Rollback não apaga divergências: preserva-as e retorna à referência anterior somente quando hashes e versão do estado ainda coincidem. A recuperação do incidente atual deve preceder a ativação dessa arquitetura.
