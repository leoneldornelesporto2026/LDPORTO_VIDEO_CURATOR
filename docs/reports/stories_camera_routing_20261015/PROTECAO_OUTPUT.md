# Organização e proteção de output — 15/10/2026

A auditoria foi feita sobre o estado concluído pelo usuário, antes de qualquer nova revisão de câmera. Os 8 Reels atuais e as 16 prévias atuais dos Stories, incluindo o Story 6, existem e tiveram seus SHA256 recalculados independentemente: **24/24 coincidem com as referências persistidas**. A fonte ativa externa do Analyzer também coincide com o SHA256 do plano. Nenhum projeto real foi salvo pela auditoria.

## Inventário preservado

O baseline [protected_before.json](protected_before.json), criado antes das edições desta sessão, contém **2.344 arquivos e 2.344.502.446 bytes**, sem links ou junctions percorridos. O inventário usa o estado novo do usuário; não reverte renders ou aprovações para o estado de um relatório anterior.

| Árvore | Arquivos | Bytes |
| --- | ---: | ---: |
| `output` | 1.841 | 1.049.118.646 |
| `.cache` | 502 | 94.732.588 |
| `source_cache` | 1 | 1.200.651.212 |

Dentro de `output`, a estrutura existente permanece preservada:

| Área | Arquivos | Bytes | Função |
| --- | ---: | ---: | --- |
| `curation/zd_wjssZ7mc` | 352 | 90.972.058 | Decisões, snapshots, percepções visuais e revisões do plano dos Reels |
| `projects/zd_wjssZ7mc/stories_30af3ad6a05923e2` | 1.372 | 699.185.705 | Índice das 3 séries, 16 Stories, prévias, legendas, títulos, capas, planos e histórico |
| `renders/zd_wjssZ7mc` | 117 | 258.960.883 | Reels renderizados, prévias, recibos e metadados |

Há 48 MP4s de Stories: os 16 atualmente referenciados e 32 históricos, em três pastas de revisão por episódio. Há 16 Reels finais, divididos entre a revisão antiga e a revisão atual, além de 2 prévias de Reel. A revisão atual dos Reels é `4ef6de98012d4484b35c962b42553b4f`, com 8 resultados, estado `BATCH_COMPLETED` e `active_batch=null`. Os 16 Stories estão em `PREVIEW_READY`. As 3 séries e a ordem persistida foram somente lidas.

A fonte usada pelos planos fica no Analyzer externo e tem SHA256 `b2958122415980a8afff4f77c23ead3c31c00345e5df0ab460995eb731efb00f`. O arquivo de `source_cache` é outra cópia de mídia, com 1.200.651.212 bytes e SHA256 `a662f54c8c82ad509041979834a9493aa51651d2307647c5b934d8a517b56384`. Essa diferença não autoriza substituir ou apagar nenhuma delas; ambas foram preservadas.

O código e a configuração anteriores estão em [code_before.json](code_before.json) e `backup_before/`, com 147 arquivos copiados pela sessão principal antes das edições. A comparação completa após as demonstrações deve usar o baseline atual de 2.344 arquivos.

## Proteções verificadas no código ativo

| Caminho | Comportamento constatado |
| --- | --- |
| `storage.cleanup_preview` | Somente lê arquivos. `output`, `.cache`, `source_cache`, projetos, revisões, aprovações, originais, backups, evidências e relatórios são protegidos. |
| `storage.execute_cleanup` | Exige confirmação e política atual; revalida caminho, SHA256, tamanho, mtime, manifest, locks e uso de mídia. A fonte selecionada nunca é removível, inclusive com o argumento legado `include_source=True`. **Não foi chamada nesta auditoria.** |
| Registro de temporários | Apenas PNG/WAV/TMP gerados em `temporary_frames/` ou `render_staging/`, fora das árvores protegidas e com registro exato em manifest, podem ser candidatos. Nenhum arquivo antigo é registrado automaticamente. |
| `storage_dialog` / `gui.clean_heavy` | A interface apresenta o preview e os arquivos preservados; a opção de excluir a fonte original não existe. Não foi aberta ou acionada pela auditoria. |
| `render._render_clip` | Recusa diretório com render ou assets anteriores, cria recibo exclusivo e usa uma tentativa UUID. FFmpeg recebe `-n`; a publicação por hard link recusa colisão e o MP4 validado é preservado se falhar a escrita posterior de metadados. |
| `SeriesProject.render_episode` | Usa pasta inédita de revisão/tentativa, FFmpeg com `-n`, valida a mídia e publica por hard link sem substituir MP4 existente. Tentativas interrompidas são evidência. |
| `SeriesProject.save` | Guarda o índice anterior por hash e atualiza atomicamente o índice corrente. Também escreve playlist e manifests derivados; por isso não foi chamado no projeto real durante os ensaios. |
| `persisted_plan` | Remoções pontuais são de temporários próprios e locks com verificação do proprietário; não foi encontrada exclusão recursiva de output. |
| Instaladores históricos | Remoções pontuais pertencem ao rollback de código com escopo/hash verificados. Nenhum instalador ou rollback foi executado. |

A busca em Python, PowerShell e BAT ativos não encontrou chamada de exclusão recursiva para limpar os dados do usuário. Cópias de módulos em backups, relatórios e pacotes são histórico com finalidade própria e foram preservadas.

## Verificação somente leitura da política de limpeza

A API `cleanup_preview` foi chamada separadamente nas três árvores protegidas, com Python `-B`, sem gerar bytecode. O resultado real foi **0 arquivos removíveis e 0 bytes liberáveis** em todas elas. Foram preservados 548 possíveis temporários dentro de `output` e 8 em `.cache`; sua extensão não foi tratada como autorização para remoção. Não há manifest de registro de scratch na raiz do workspace.

Na inspeção não havia `app.py`, FFmpeg ou FFprobe ativos. Não foram encontrados `RUNNING.lock`, `.PLAN_OPERATION.lock`, `.PLAN_STATE.lock`, marcadores `INCOMPLETE` ou arquivos `ENCODING_*` em output. Os recibos permanentes `RENDER_ATTEMPT.json` existentes pertencem ao histórico e não foram removidos.

## Duplicatas e organização

O agrupamento por tamanho e SHA256 do baseline identificou 524 grupos de conteúdo idêntico, envolvendo 1.492 arquivos. A repetição lógica corresponde a 350.359.022 bytes além de uma ocorrência por grupo; isso não mede espaço físico recuperável e não é uma recomendação de limpeza. Entre os MP4s há 16 pares de prévias históricas idênticas, somando 80.830.541 bytes repetidos. As prévias atuais também têm função editorial e continuam referenciadas pelo índice.

A lista completa está em [DUPLICATAS_COMPROVADAS.json](DUPLICATAS_COMPROVADAS.json). Igualdade de bytes não torna revisões, snapshots, legendas, capas ou evidências descartáveis. Nenhum arquivo foi movido, renomeado, consolidado ou excluído. As novas evidências desta tarefa ficam em `docs/reports/stories_camera_routing_20261015/`; o projeto real continua nos caminhos originais.

## Evidência e limites

[OUTPUT_AUDIT.json](OUTPUT_AUDIT.json) contém as contagens, os caminhos e SHA256 recalculados dos 16 Stories, dos 8 Reels e da fonte ativa, além dos resultados dos três previews de limpeza. Esta auditoria não executou testes, curadoria, lote, aprovação, instalador, commit ou push e não editou módulos de produção. Os testes da correção de câmera e as demonstrações usam diretórios isolados pela sessão principal.

As proteções auditadas não impedem ações externas realizadas pelo sistema operacional ou por outro programa. A causa de um incidente antigo de output vazio permanece indeterminada. A confirmação de preservação de todos os 2.344 arquivos após a implementação depende da comparação final da sessão principal; este relatório não antecipa esse resultado.
