# Auditoria de persistência e importação — Master P0 17/10/2026

Escopo: leitura do estado restaurado, contratos, assinaturas/aprovações, integração de importação, câmera/áudio/legendas e destino de projetos novos. Nenhuma limpeza, migração, restauração, regravação de output ou execução de Analyzer/Qwen foi feita por esta auditoria. Os testes usam diretórios isolados no TEMP e apenas fixtures sintéticas. A implementação deste agente está restrita aos novos leitores de contrato, schema, PDF, testes e estes documentos; o integrador principal é responsabilidade do agente raiz.

## Estado legado observado

O workspace começou na branch `main`, HEAD `647d05652c51376a2ebe4ae43ccffda96aa05939`, sem alteração rastreada; existia a pasta não rastreada `docs/second_curation/9UCGZia2p1k/`. Scripts nessa pasta não foram executados. O agente raiz concluiu o inventário/backup antes de autorizar os arquivos novos; referências do backup estão em `docs/reports/master_p0_20261017/` e no backup externo `Videos/_backups/master_p0_20261017T054523Z`.

O output restaurado observado é da fonte `9UCGZia2p1k`, SHA256 `5d089e1825b396dafd6b5918274f3a785eb2d8be2f622497cb7d06fdd7b3b7ea`. Não se trata automaticamente dos lotes de outra fonte vistos nos dias anteriores.

| Registro existente | Evidência observada |
| --- | --- |
| `output/curation/9UCGZia2p1k/EDIT_DECISIONS.json` | Revisão `3ecd06d3e4b848d0a004dace195a8472`, `TEST_APPROVED`, approval_record existente; resultados finais vazios no estado lido. |
| Prévia de `SECOND_SHOW_01_MOMENT_00015_0000_01` | `_checked_preview` do `Pipeline`, chamado em leitura com o `render_config` persistido, validou a prévia atual; SHA256 `82507671ea7b4fa156749e88b27d1810608f2513ac9047c9ff560b99c4260491`. |
| `output/projects/9UCGZia2p1k/stories_4844ed7bf0279fba/series_index.json` | Plano `STORIES_4c576102fe657eb415ed50d7`, sete propostas, séries com 2/3/2 partes, sem prévias/aprovações registradas nesse plano. |
| Fonte original referenciada | `LDPORTO_VIDEO_ANALYZER/input/youtube/9UCGZia2p1k/9UCGZia2p1k.mp4` existe; não foi copiada ou alterada por esta auditoria. |

Essa verificação comprova a validade da prévia e de sua assinatura no estado observado. Não concede aprovação nova ou prova a integridade de todas as mídias históricas; o inventário SHA abrangente é tratado pelo agente raiz.

## Entradas reais novas

ZIP nativo: `SECOND_CURATION_READY_5d089e1825b3_20261017_020701_253736_8b80a1.zip`, em `LDPORTO_VIDEO_ANALYZER/pacotes_para_enviar`. SHA256 do ZIP `5e5af9a17897eb424972c4d722a818ce29ca1d75dfff5e2e96b525932872f0cb`; 173 arquivos, 116.119.475 bytes descompactados. O ZIP real possui JSON/JSONL/JPEG/Markdown/HTML/SRT/texto; não tem PDF e passa pelo gate de tipos nativo existente.

Handoff externo: `Videos/LDPORTO_VIDEO_ANALYZER/Projeto_audiovisual__5d089e1825b3__20261017T021624775842Z_4a0271`. `PROJECT_MANIFEST.json` declara 1.772 arquivos, 217.383.909 bytes; são 1.773 arquivos incluindo o próprio manifest. Inclui PDFs e o ZIP nativo completo em `06_SEGUNDA_CURADORIA/SECOND_CURATION_READY.zip`, cujo hash coincide com o vínculo declarado. Todos os arquivos declarados foram verificados pelo leitor novo, sem cópia ou execução.

Os metadados técnicos são duração `5840.094`, `1920x1080`, FPS `24.000001369843545`, fonte SHA256 `5d089e...`. Não existe YouTube ID ou título nominal declarado na metadata nativa: não devem ser inferidos a partir do prefixo SHA ou do nome genérico `original.mp4`. O título do handoff é `Projeto audiovisual`, enquanto `source_metadata_title` e `video_id` estão nulos.

O handoff relata cobertura de transcrição de aproximadamente 16,92%, 70 candidatos, 25 intervalos com geometria válida, zero zoom confirmado, 86 partes de Story em 49 séries e um Story independente. Seu preflight de candidatos declara 68 `ALIGNMENT_REVIEW_REQUIRED` e dois `AUDIO_REVIEW_REQUIRED`. Esses números são declarações/evidências upstream, não aprovação visual ou auditiva executada neste refinamento. Não há base para renderizar legendas karaokê confiáveis em todos os candidatos automaticamente.

## Contratos existentes e riscos concretos

| Ponto | Código/contrato | Implicação e solução segura |
| --- | --- | --- |
| Fingerprint global de Stories | `episode_approval.py:21` inclui bytes de render, titles, subtitles, series_workflow, presets, media_effects e episode_approval, além da versão FFmpeg. | Editar esses módulos invalida assinaturas históricas mesmo sem alterar mídia. O adaptador novo fica fora desse conjunto. |
| Assinatura de episódio | `episode_approval.py:28` assina o episódio, fonte, transcrição e **cfg completo**. | Não reserializar ou modernizar o cfg legado, nem trocar slashes/caminhos ou int/float. Reabrir com o cfg fixado na revisão. Novas revisões podem fixar configurações próprias. |
| Fingerprint de Pipeline | `pipeline.py:28`, `persisted_plan.py:189` vinculam renderer e settings; `persisted_plan.py:103` remove infraestrutura da projeção semântica de Reels. | Os contratos de Reels e Stories não tratam cfg/caminhos igualmente; não presumir intercambialidade. Conservar estados legados literais. |
| Confinamento de aprovação | `episode_approval.py:42` e `:61` vinculam mídia/assets por caminhos relativos e SHA256. | Um projeto novo pode viver externamente sem mudar o algoritmo. Não reescrever paths dentro de registros antigos. |
| Publicação/concorrência | `persisted_plan.py:331` fornece `project_lock`; `SeriesProject.save` já existe, sem transação de importação do pacote inteiro. | Usar wrapper novo com staging, inventário, lock, journal e publicação por rename no mesmo volume; não alterar o writer histórico. |
| Renderer contínuo | `render.py:392` abre a fonte em um único `source_start`, com uma duração contínua. | Montagem com lacunas ou reordenação não é suportada. O READY rejeita essa operação; propostas nativas descontínuas devem ficar bloqueadas até edição/revisão explícita. |
| Timeline de câmera | `render.py:247` ajusta extremidades dos intervalos recebidos. | Validar cobertura relativa completa antes do renderer, com intervalos amplos explícitos para lacunas; não permitir que adaptação silenciosa invente continuidade. |
| Zoom | Motor atual suporta envelope animado conservador até 1,05 e crop estático até 1,13. | Validar os limites reais e converter tempo absoluto upstream para relativo somente no adaptador de evidência. |
| Áudio | `render.py:425` inclui loudnorm; `media_effects.py:147` remove/substitui essa cadeia conforme o plano de áudio no fluxo `SeriesProject`. | Usar o caminho existente de SeriesProject para Reels importados permite áudio `original`; chamar somente render_clip não equivale a preservar o áudio original. |
| Legendas | Serializer existente exige evidência lexical/alinhamento, e o handoff real declara bloqueios. | Não fabricar palavra ou timestamp. Rejeitar/bloquear a peça em revisão, preservar o motivo, continuar peças independentes. Classes sem fala exigem comprovação explícita e adaptação compatível. |
| Decisões V4.4 | Compiler de decisões possui schema estrito sem campos arbitrários de câmera/overlay importados. | Manter documentos originais + índice visual normalizado assinado no projeto novo; reutilizar SeriesProject/Camera Director no render. Não injetar campos desconhecidos em EDIT_DECISIONS legado. |

Os paths citados são internos ao repositório `ldporto_curator/`. As linhas foram capturadas durante a auditoria; módulos novos do integrador ainda podem receber ajustes concorrentes.

## Integração proposta e implementada nos adaptadores

1. Ler e validar o contêiner em memória, sem extrair, inferir conteúdo ou executar scripts. Identificar a fonte pelo SHA completo e metadados técnicos; associação ao arquivo original exige hash real, não somente nome.
2. Criar somente projeto novo externo sob a Known Folder de Vídeos, no diretório `LDPORTO_VIDEO_CURATOR`, mantendo a fonte original onde está. Usar um índice/referência verificável para mídia existente; não mover output/cache/projetos antigos.
3. Congelar identidade de pacote/fonte/settings e evidência normalizada por revisão. Fazer staging externo com journal e publicar a revisão completa por rename no mesmo volume. Reimportação idêntica deve retomar o mesmo projeto; falha deixa staging identificável e revisão anterior intacta.
4. Usar `SeriesProject` e o renderizador/caption/title/approval existentes. Um wrapper separado pode acrescentar locks, gates por peça, histórico e edição transacional sem alterar o fingerprint global. Exportação do dossiê lê o estado congelado e grava somente PDF novo externo.
5. Renderizar somente prévias explicitamente solicitadas, tratando sucesso/bloqueio/falha por peça e propagando cancelamento. Revisão visual humana continua necessária; importação e geometria disponível não equivalem a aprovação.

O integrador novo `production_package.py` é mantido pelo agente raiz. Esta auditoria comunicou os riscos de assinatura/path absoluto antes das alterações do integrador; não editou módulos históricos de fingerprint.

## Verificação dos arquivos deste agente

`production_contract.py` realiza os três leitores e validação READY descritos em `CONTRATO_LDPORTO_CURATOR_READY_V1.md`; schema V1 novo em `schemas/`. `production_dossier.py` exporta PDF pesquisável com dados persistidos, incorpora JPEGs intactos após hash e referencia os demais assets. Não há dependência ReportLab instalada; a limitação CP1252 é declarada no PDF e no retorno da função, preservando JSON UTF-8 como autoridade literal.

Comando de verificação: `.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider tests/test_production_contract.py tests/test_production_dossier.py --basetemp <diretório TEMP isolado> -q`. Resultado: **40 passed**, 0,67 s. Há verificações de não escrita de fontes/estado, não sobrescrita, idempotência, PDF pesquisável e JPEG incorporado byte a byte. O ZIP nativo e o handoff reais passaram adicionalmente em leitura. Isso não substitui o teste audiovisual e a aprovação humana que o agente raiz coordena; nenhuma aprovação foi concedida por esta auditoria.
