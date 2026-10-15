# Correção P0 — persistência e aprovação do render V5.2

O fluxo principal passou a consumir uma única revisão persistida entre CURAR, TESTAR, APROVAR e RENDERIZAR TODOS. Os gates permanecem ativos. A validação funcional usa FFmpeg real e também os botões, threads e widgets Tk de produção. A homologação integral do vídeo real zd_wjssZ7mc permanece dependente de seu original, indisponível no workspace.

## 1. Causa raiz e provas anteriores à correção

`App.work` despachava para `Pipeline.test_one` e `Pipeline.render_all`. Ambos chamavam `_prepare_curation`, que executava `curate → review_candidates → Qwen` e sobrescrevia `EDIT_DECISIONS.json`. A resposta era filtrada pelos campos approve, ordenada e recebia novos ranks/IDs. Portanto a mesma operação de render podia modificar seleção, quantidade, títulos e ordem. APROVAR não chamava o Qwen, mas lia a seleção mais recentemente sobrescrita.

Uma segunda causa independente foi comprovada nos arquivos reais: TESTAR refinava o plano de câmera e a margem de legenda de CLIP_001; o bootstrap de RENDERIZAR TODOS substituía esse plano refinado pelo básico. O básico tinha 14 segmentos e o efetivamente usado na prévia tinha 10. Restaurar somente `clips/CLIP_001/clip.json` em memória reproduziu exatamente a assinatura registrada na prévia: `dc6a397b869d8f340b4980ad79a7b290d1173d271ae48c968312ad040478ec1a`. A assinatura do EDIT básico era `6ae34156e27432b38c53c67dac0fe005081bc7bc822734bf62fd9929259509cf`. A auditoria preserva 295 diferenças de campos.

Os sete cortes iniciais estão nos logs fornecidos; seu snapshot não existe nos arquivos disponíveis. O cache atual contém três e metadados Qwen returned=8/approved=3. A nova inferência e o mecanismo capaz de alterar a seleção são comprovados; a resposta integral da primeira execução antiga não pode ser reconstruída. Os arquivos antigos de aprovação estão atualmente ausentes. Não atribuí sua ausência ao pipeline sem evidência de exclusão.

Provas: [auditoria de baseline](P0_BASELINE_AUDIT.json), [inspeção inicial](P0_READONLY_AUDIT.md), [código e hashes anteriores](legacy_code_baseline/SHA256.json).

## 2. Código implementado

| Arquivo | Funções/alteração funcional |
| --- | --- |
| `ldporto_curator/pipeline.py` | CURAR é o único caminho de análise/seleção/refinamento. `_load` usa snapshot local. `test_one`, `approve_test` e `render_all` usam a revisão congelada. `read_state` recupera o projeto; `revise_plan` faz edição explícita sem modelo. Render/artefatos são separados por revisão e execução. |
| `ldporto_curator/persisted_plan.py` | `PlanStore.create/load/save_state`, snapshots imutáveis, ponteiro atômico, histórico, fingerprints, CAS por revisão/versão e lock entre processos com PID/token. |
| `ldporto_curator/pipeline_recovery.py` | `recover_local_plan` migra dados legados locais com backup. Recupera transcrição real do handoff e câmera compatível com a assinatura histórica. Não fabrica palavras, fonte, hash ou aprovação. |
| `ldporto_curator/approval.py` | Contrato legado preservado; publicação JSON atômica e binding opcional de revisão/fonte/render. Aprovação exige MP4 íntegro e registro correspondente. |
| `ldporto_curator/render.py` | Sidecar do render efetivo: encoder utilizado, dimensões, duração/início, hashes ASS/card/MP4 e fingerprint das configurações. Inclui fallback NVENC → libx264 real. |
| `ldporto_curator/ollama_client.py` | Conserva resposta editorial completa, texto bruto e SHA-256, inclusive candidatos recusados. CURAR grava `EDITORIAL_RESPONSE.json` e a resposta no snapshot. |
| `ldporto_curator/review.py` | Board resolve as miniaturas da execução versionada, mantendo o contrato anterior de dois argumentos. |
| `ldporto_curator/gui.py` | Configuração/fonte/rank capturados no thread Tk; workers enviam somente Queue. Tokens descartam resultados atrasados/duplicados. Controles incompatíveis ficam bloqueados. Sessão, revisão, estado e fingerprint recuperam após reabrir. Botão Aplicar configurações ao plano cria nova revisão e exige nova prévia/aprovação. |

O refinamento técnico continua disponível: quando o original está acessível, executa na CURAR antes de selar a revisão. TESTAR e lote não refinam ou substituem planos após a revisão. Se a fonte não estava disponível na CURAR, a revisão conserva a câmera baseada nas evidências existentes; não promete percepção local que não executou.

## 3. Persistência e recuperação

O ponteiro compatível `output/curation/<projeto>/EDIT_DECISIONS.json` mantém `approved_clips` e passa a identificar schema 5.2, projeto e UUID da revisão. `revisions/<UUID>/` contém `ANALYSIS_SNAPSHOT.json`, `PLAN_INPUTS.json`, `STATE.json`, versões anteriores de estado, handoff e relatórios. As entradas e seus SHA-256 são validados antes da publicação e a cada leitura. Não há nova leitura do Analyzer nas operações seguintes.

Cada preview e lote usa um UUID próprio dentro da revisão. Regenerar a prévia mantém os MP4 anteriores e exige aprovação explícita do novo MP4. Nova CURAR ou edição preserva a revisão anterior e sua aprovação no histórico. Undo/redo e os contratos de SeriesProject existentes não foram substituídos.

Projetos legados recebem arquivo de rastreabilidade `legacy_archive/` antes da troca do ponteiro. A prévia histórica verificável fica registrada como evidência. Sem identidade integral de fonte/render, ela não é promovida a aprovação de uma revisão nova. A migração exige nova prévia e revisão humana; a mensagem explica a causa.

## 4. Fingerprints

SHA-256 é calculado sobre JSON canônico: chaves ordenadas, UTF-8, números finitos, precisão de nove casas e equivalência int/float integral. A ordem da lista de cortes é significativa.

- `source_fingerprint`: dados congelados de análise/evidência/transcrição/legendas/timings e identidade de fonte declarada. `.root`, caminhos e campos de diagnóstico não entram nessa identidade semântica. O snapshot possui também SHA-256 dos bytes e a origem possui fingerprint de conteúdo.
- `editorial_plan_fingerprint`: todos os cortes em ordem, IDs/ranks, início/fim/duração, títulos/duração de título, planos de legendas/áudio e campos de câmera que controlam a composição. Inclui as câmeras de todos os cortes do lote.
- `preview_render_fingerprint`: projeto, UUID, fonte, seleção, configurações fixadas, clip testado, SHA-256 do original selecionado, versão FFmpeg e hashes dos renderizadores.
- `preview_media_sha256`: bytes do MP4 produzido, separado dos inputs.
- `approval_record`: exatamente o registro da prévia, incluindo bindings e SHA-256 do sidecar efetivo. Flag isolada ou nome CLIP_001 não liberam lote.

Horário, tempo de execução, refresh visual, nova leitura, caminhos de saída/Analyzer, habilitação/modelo Qwen e configurações de seleção não alteram a identidade renderizada. Diagnósticos/confiança/motivos de câmera são separados dos campos que controlam pixels. Mídia/fontes/efeitos relevantes usam conteúdo, não apenas nome ou mtime.

## 5. Gates e alterações legítimas

TESTAR carrega a revisão, escolhe o rank exato, resolve/verifica o original, renderiza, registra hashes e publica PREVIEW_READY. Não troca silenciosamente de clip se o rank não existe.

APROVAR trabalha com o preview existente. Valida revisão, clip, plano, source SHA registrado, MP4, sidecar, encoder, dimensões, início/duração e configurações efetivamente renderizadas. Não precisa ler novamente o original para revisar o MP4; a validação atual dos bytes do original ocorre antes do lote. Somente o handler explícito de aprovação registra TEST_APPROVED.

O lote exige estado e registro compatíveis, flag da revisão, integridade da prévia/sidecar/aprovação e identidade do original. Não consulta o modelo nem reconstrói câmera. Alterações reais bloqueiam com caminho do campo, por exemplo `subtitles.font`, `editorial_projection[0].source_start`, `source_media.sha256` ou `preview_media_sha256`. Edição/configuração explícita cria outro UUID sem Qwen, informa revisão anterior/ativa e exige nova prévia/aprovação. Nenhuma aprovação é copiada entre revisões.

## 6. Concorrência e GUI

O lock exclusivo de projeto protege toda operação, inclusive encode. Um PID vivo não perde o lock; somente um PID comprovadamente morto pode ser recuperado. CAS verifica revisão, fingerprints e versão de estado antes de publicar resultados. Um worker atrasado pode deixar seu arquivo isolado, mas não altera o ponteiro nem libera o lote de outra revisão.

Os workers recebem cópia de cfg e strings/rank capturados no thread principal. Progress/log/error/done/import/preview levam token da operação. Eventos de uma operação anterior e done duplicado são ignorados. Diálogo tardio de mídia não muda configurações nem reinicia ação de outra operação. Abrir resultados não chama curadoria.

Estados visíveis incluem SEM_PLANO, PLAN_READY, GENERATING_PREVIEW, PREVIEW_READY, TEST_APPROVED, BATCH_RENDERING, BATCH_COMPLETED, NEEDS_REVIEW e APPROVAL_INVALIDATED. Projeto, revisão, fingerprint e causa aparecem na interface/log, sem tokens ou segredos. O hash exibido foi unificado entre evento e leitura de reabertura.

Lotes com erro recuperam TEST_APPROVED quando a prévia/aprovação continuam íntegras; não exigem uma inferência nova para tentar novamente. Parciais ficam no batch_history com SHA verificado e não entram como resultados completos. Alteração de fonte invalida a aprovação com motivo. A reabertura recupera BATCH_RENDERING interrompido depois de adquirir o lock, registra INTERRUPTED e preserva rastreabilidade. Worker obsoleto não pode publicar essa recuperação sobre outra revisão. COMPLETED só é publicado após render, board, handoff e CAS.

## 7. Testes direcionados e regressão completa

Resultados finais: **102 testes direcionados aprovados em 16,47 s** e **462 testes na regressão completa aprovados em 38,63 s**. Há **94 testes P0 novos**. Nenhum teste existente foi removido para obter esses resultados. `compileall` e `git diff --check` passaram. Evidências: [validação](VALIDACAO_FINAL.json), [direcionados](TESTES_DIRECIONADOS.txt), [regressão completa](REGRESSAO_FINAL.txt). A primeira execução anterior havia aprovado 453 testes; os adicionais verificam a resposta editorial completa e falhas/interrupções do lote.

Comandos: `.venv\\Scripts\\python.exe -m pytest -q tests/test_p0_plan_store.py tests/test_p0_pipeline.py tests/test_p0_gui.py tests/test_p0_legacy_recovery.py tests/test_p0_editorial_response.py tests/test_v44_approval.py tests/test_v44_ops.py tests/test_progress.py` e `.venv\\Scripts\\python.exe -m pytest -q`.

Novos testes: `test_p0_plan_store.py`, `test_p0_pipeline.py`, `test_p0_gui.py`, `test_p0_legacy_recovery.py` e `test_p0_editorial_response.py`. Cobrem números canônicos, leitura/reabertura, configurações, fonte/crop/legendas/áudio/título/duração, adulteração de MP4/sidecar/registro, revisão sete → três, falta de plano/rank, aprovação offline, subprocesso real com lock, atomicidade, CAS e cliques/callbacks/threads reais da GUI.

## 8. Aceite A–H

| Cenário | Resultado |
| --- | --- |
| A — fluxo completo | CURAR sete cortes, FFmpeg real, aprovação automatizada exclusiva da fixture e sete finais na mesma revisão. |
| B — sete → três | Apenas uma nova CURAR explícita muda a seleção; outro UUID e aprovação pendente, histórico anterior preservado. |
| C — leituras/reabertura | Estado, aprovação, seleção e hash estáveis. Abrir/atualizar GUI não chama Qwen. |
| D — alteração real | Bounds/crop/câmera/título/legendas/áudio/fonte/pixels e configurações efetivas bloqueiam o gate com causa. Edição explícita sem Qwen testada. |
| E — Qwen proibido | curate/find_analysis/load_bundle/model review levantam erro se chamados nas etapas posteriores; fluxo passa com zero chamadas. |
| F — persistência | Pipeline reconstruído entre todas as ações; GUI fechada/reaberta após aprovação, lote real concluído. |
| G — concorrência | Clique duplo, callback tardio, worker atrasado, CAS, lock real entre processos, falhas de publicação/encode/assets/board, retomada e fonte alterada durante lote cobertos. |
| H — zd_wjssZ7mc | Recuperação local em cópia e verificação do preview real completas. Nova prévia/lote integral pendentes do original; o gate bloqueia e nenhuma aprovação humana é inventada. |

## 9. Render e GUI reais

O harness `scripts/validate_render_p0.py` gera original sintético de quatro segundos e executa renderizações reais de clips de 0,5 s. Mocka somente a obtenção/seleção editorial para controlar sete → três; FFmpeg, FFprobe, persistência, gate e hash executam código de produção. Preview 540×960, sete finais 1080×1920, H.264/libx264 e AAC. Configuração e limites sintéticos são declarados no relatório, sem alegar equivalência editorial a um episódio real longo.

O driver `scripts/capture_render_p0_ui.py` usa App real, `Button.invoke`, workers reais e renders reais de três clips em cópia isolada. Aprova somente a fixture de teste, fecha e reabre a janela antes do lote. Nenhum mock de Pipeline/render/widgets. Suprime apenas abertura de player externo e faz Analyzer/modelo falharem se chamados. Captura somente o retângulo da janela.

Prova final do backend: [P0_ACCEPTANCE.json](acceptance_20261014T041942759404Z/P0_ACCEPTANCE.json). Inclui manifesto dos 29 originais, probes/hashes e a recuperação real isolada. Prova final da GUI: [GUI_ACCEPTANCE.json](gui_20261014T042341080113Z/GUI_ACCEPTANCE.json), [aprovado](gui_20261014T042341080113Z/APPROVED.png), [lote concluído](gui_20261014T042341080113Z/BATCH_COMPLETED.png). São três finais e zero chamadas nas cinco rotas de análise/modelo monitoradas. O relatório guarda UUID, seleção, hash visual estável e reabertura aprovada.

As aprovações dos ensaios são ações automatizadas de fixture, sem alegação de revisão humana da qualidade. Nenhum vídeo real recebeu aprovação automática.

## 10. Projeto real, preservação e limites

Prévia real: 7.522.073 bytes, 41,249542 s, H.264 540×960, 989 frames, AAC estéreo 48 kHz; SHA-256 `d20972bfc76b364b8008354cad396caee7ad5d66be151e5ee664113bcbf4c40a`, igual ao registro. Original e SHA-256 da análise original desconhecidos; não preenchidos por aproximação. Recuperados três clips e 46 segmentos existentes do handoff; captions usam esses timestamps de segmento, sem palavras/timings inventados. A cobertura é explicitamente parcial.

Todos os 29 arquivos originais de curation/renders foram comparados antes/depois e continuam byte a byte idênticos. Os relatórios, demos e pacotes V5.1 não foram sobrescritos. Configuração, contratos da série, gates e histórico existentes foram preservados. Nenhum commit, Git destrutivo, reinstalação, inferência real, alteração de Analyzer ou reprocessamento do vídeo completo foi executado.

Referências de MP4/sidecar/results usam caminhos absolutos para recuperar no mesmo workspace; mudança da pasta do projeto exige restaurar referências/mídia e não é homologada nesta entrega. O encoder real de teste foi libx264; o fallback NVENC é registrado no sidecar, mas não alego render NVENC sem evidência de execução. A qualidade editorial/câmera/legendas de episódios reais longos continua exigindo revisão humana.

## 11. Próxima ação exata

Para fechar H, abrir o Curator, informar zd_wjssZ7mc, selecionar o vídeo original e executar TESTAR 1 CORTE → assistir → APROVAR TESTE → RENDERIZAR TODOS sobre a revisão recuperada. O caminho não requer nova inferência nem reprocessar o Analyzer; a prévia histórica permanece preservada. Caso deseje nova seleção, usar CURAR explicitamente.

Após homologar H com a fonte, retomar a Etapa C da V5.2: integrar canvas de crop sobre frame real e formulários de estilo ao editor/histórico existentes. A/B continuam concluídas; os arquivos parciais de C foram preservados. Esta entrega corrige o P0 e não declara todas as etapas C–F concluídas.
