# Proteção e organização dos arquivos — 17/10/2026

Não foi executada limpeza, migração, restauração de output, exclusão de resultados ou substituição de aprovações. O inventário SHA256 anterior precedeu a implementação. Um backup externo do código e dos estados ficou em `C:/Users/leone/Videos/LDPORTO_VIDEO_CURATOR/_backups/master_p0_20261017T054523Z`, subpastas `code/` e `state/`.

## Inventário inicial

| Diretório | Arquivos | Bytes |
| --- | ---: | ---: |
| output | 137 | 161.710.138 |
| .cache | 667 | 123.881.926 |
| source_cache | 1 | 1.200.651.212 |
| docs | 5.365 | 1.454.404.833 |
| .venv | 6.758 | 252.923.608 |

O inventário `PROTECTED_BEFORE.json` registra 6.327 arquivos com SHA256, além dos tamanhos agregados e exclusões explícitas de infraestrutura. `INPUTS_BEFORE.json` registra o ZIP e 1.773 arquivos do dossiê, total de 1.774 entradas. Não foram observados reparse points no inventário.

Em docs, antes da rodada, havia 819.111.628 bytes de JSON, 332.168.755 de PNG, 202.653.967 de MP4, 36.681.554 de JPG, 35.474.967 de ZIP e 11.499.580 de WAV. Dez cópias de `evidence.json` com 46.700.285 bytes cada aparecem em projetos/parent snapshots de demonstração e recuperação. São referências históricas e não foram removidas ou desduplicadas.

Esses números mostram que o acúmulo inclui evidências e estados de revisão, além de arquivos de vídeo. Extensão JSON, nome “cache” ou presença em docs não autorizam eliminação.

## Rotinas de alteração/exclusão auditadas

Busca em código, scripts e testes por rmtree, Remove-Item, unlink, rmdir, replace, rename, move, robocopy e purge; ocorrências de `str.replace` foram separadas de operações de filesystem. Não foi encontrada chamada recursiva de remoção de output no código atual de produção. Isso não atribui autoria aos incidentes anteriores nem prova a ausência de operações externas.

| Local | Operação e alcance | Proteção / resultado da auditoria |
| --- | --- | --- |
| `storage.py:execute_cleanup` | unlink de scratch previamente registrado | Exige confirmação, política vigente, registro, tamanho, mtime e SHA. output, caches, projetos, originais, docs, backups e manifests são protegidos. Não foi chamado. |
| `storage.py:media_lease` | Remove exclusivamente o marcador de lease criado pela própria operação | Não remove a mídia ou o diretório. |
| `persisted_plan.py` | Replace atômico do estado; remoção de arquivos temporários/locks próprios | CAS/revisão e posse de lock; nenhum esvaziamento de output. |
| `series_workflow.py:save` | Substitui índice depois de preservar snapshot histórico por SHA | Comportamento existente. Novas importações ficam em diretórios externos exclusivos; nenhum plano legado foi salvo. |
| `editing_history.py` | Publica snapshot de edição por replace | Snapshot por hash, histórico e cursor preservados. |
| `render.py`, `series_workflow.py`, `combined_batch.py` | Publica MP4 com hard link exclusivo e remove apenas a própria saída parcial | Não substitui MP4 final existente; falha/interrupção preserva materiais para inspeção. |
| `gui.py` | Publica preferências de estilo pelo temporário próprio | Não altera/esvazia output; o novo importador não reescreve config global. |
| `camera_revision.py` | Renomeia marcador de revisão incompleta para completa | Dentro da nova revisão, sem migração de mídias antigas. |
| `production_package.py` | open exclusivo no staging e rename de uma nova pasta completa | Lock por projeto, journal, hash e destino externo; falha deixa staging identificado. Não executa scripts do pacote. |
| `production_dossier.py` | Hard link exclusivo do novo PDF e remoção do próprio pending | Nome por hash; PDF anterior preservado; não salva plano ou aprovação. |
| `INSTALL_CAMERA_FINAL.ps1` | Remove arquivo recém-instalado durante rollback explícito | Allowlist e hashes de código. Não foi executado nesta rodada. |
| `INSTALL_CAPTIONS_P0.ps1` | Restaura backup ou remove arquivo recém-criado em rollback/falha | Escopo de payload de código; não foi executado nesta rodada. |
| Scripts de recuperação | Copiam evidências/estados históricos e produzem snapshots | Não foram executados. Os materiais existentes permanecem intactos. |
| Testes | Fixtures, temporários de render e simuladores de interrupção/rollback | Executados somente com basetemp novo em TEMP, sem cache pytest e sem gravação de bytecode. Aprovações sintéticas nunca foram aplicadas ao conteúdo real. |

Inicialização, importação, renderização e retorno à GUI não chamam a limpeza opt-in. A instância antiga de app.py observada em execução não foi encerrada à força; o novo fluxo trabalhou em projetos externos separados. A verificação SHA não detectou gravações concorrentes nos artefatos protegidos durante esta rodada.

## Scripts históricos que acumulavam materiais em docs

`validate_camera_final_real.py`, `validate_story_camera_routing.py` e `render_camera_demos_hd.py` ainda exigem destinos históricos em docs/reports; `validate_render_p0.py`, `demo_curator_v5.py`, `validate_curator_v5.py` e `capture_v5_ui.py` também usam árvores de relatório antigas para suas demonstrações. Esses scripts não foram disparados nesta rodada e não constituem o caminho padrão do novo importador. Permanecem uma dívida de organização: devem receber destino externo explícito antes de nova homologação que gere mídia. Uma troca indiscriminada de paths quebraria referências/relatórios históricos, portanto não foi feita automaticamente.

O script novo `validate_production_camera.py` recusa destino dentro do repositório, inclusive docs. O importador e o exportador PDF novos também recusam armazenamento interno. Os testes de produção exercitam a recusa de output, docs, docs/reports e .cache. XMLs, inventários e Markdown leves continuam no repositório.

## Resultado e rollback

`PROTECTED_AFTER.json` comprova: 6.327 arquivos anteriores conferidos, nenhum ausente; mudanças de código restritas aos arquivos autorizados; zero mudança nos 805 arquivos anteriores de output/.cache/source_cache; zero mudança nas 1.774 entradas de origem. `LEGACY_APPROVAL_VERIFIED.json` comprova que a prévia legada permanece válida e que os nove módulos de fingerprint continuam idênticos.

Novos artefatos: revisão externa `63114d7dd8af829e4a40`, PDFs e demonstrações técnicas externas. A revisão experimental `15cbff3ae70a2e5f64a0` e tentativas incompletas foram preservadas; não são a prova válida da correção.

Rollback seguro: fechar os workers novos, conservar todos os diretórios de produção/ensaios, comparar hashes do backup `code/` com `CODE_BEFORE.json` e restaurar somente os arquivos de código explicitamente selecionados após conciliar alterações posteriores. Não apagar módulos novos ou reescrever histórico Git automaticamente. Para voltar ao projeto antigo, abrir seu diretório original; não é necessário mover mídia ou alterar manifest/aprovação.

Reorganização futura proposta: inventariar a geração a mover, copiar para Vídeos, verificar todos os SHA256, produzir manifest de origem/destino e manter a origem para rollback. Reescrever referências somente em uma revisão derivada e verificar aprovação/preview com o motor existente. Migração e descarte continuam sem execução nesta rodada.

O HEAD observado mudou externamente de `647d056` para `dbc7d27` durante a sessão. Não foi emitido comando de commit, reset, checkout ou push pelo agente; esse estado externo não foi revertido.
