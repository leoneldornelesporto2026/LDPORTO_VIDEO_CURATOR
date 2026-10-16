# Por que os 16 Stories ficaram em `full_frame_blur`

Auditoria de leitura, 15/10/2026. Nenhum arquivo de produção foi alterado por esta investigação. A etapa de auditoria não executou CURAR, modelos, detectores ou renderizações; as duas demonstrações separadas da sessão principal estão em `duas_previas/`. O patch anexado está preparado, **não aplicado**.

## Conclusão comprovada

As decisões refinadas dos Reels não passam pelo caminho de renderização dos Stories. Os 16 Stories escolheram corretamente `AUTO_CONSERVADOR`, mas seu snapshot de evidências veio do pacote parcial sem coleções de geometria. O caminho V5 produziu o fallback amplo e o persistiu. O renderizador recebe esse plano e o executa. Retomar ou renderizar o projeto não recalcula câmera, preservando corretamente as revisões existentes.

Existem metadados mais ricos no diretório original do Analyzer da mesma fonte; eles não estão no snapshot dos Stories. Portanto a conclusão é **ausência de evidência no projeto de Stories e ausência de uma ponte explícita para nova revisão**, não ausência de análise na máquina.

## Rastreamento por etapa

| Etapa | Evidência e comportamento observado |
|---|---|
| Seleção de modo | `story_import.py:127` atribui `AUTO_CONSERVADOR`; os 16 episódios persistidos mantêm esse valor. Não há `SOURCE_PRESERVE` selecionado por engano nos 16. |
| Pacote importado | `evidence.json` dos Stories declara `missing`, contagem zero, para `timeline`, `scenes`, `people_observations`, `frame_samples`, `camera_timeline` e `speaker_person_mapping`. |
| Segunda curadoria | `compile_decisions()` em `second_curation_decisions.py:47` transforma decisões editoriais e `suggested_layout`; não produz geometria. `series_review.py:272` importa Stories usando `current.evidence`. Não chama o refinador dos Reels. |
| Resumos de câmera do pacote | `evidence.documents` preserva os bytes sem promover sugestões a certificados: `camera/candidate_camera_plans.json` tem 69 candidatos e 643 segmentos. Esses resumos não correspondem ao contrato completo de Director. |
| Plano de Stories | `series_workflow.py:156` implementa `conservative_camera`; `:213` retorna fallback quando não há linhas de timeline cobrindo o intervalo. É o ramo que explica os 16 resultados atuais. |
| Persistência | `series_workflow.py:771` só resolve câmera quando `camera_plan` ainda não existe. Os 16 planos já existem. `:865` grava exatamente o plano usado ao lado da prévia. |
| Caminho de Reels | `pipeline.py:294-298` chama `final_camera.refine_clip()` durante planejamento e congela o resultado; Stories não passam por esse bloco. A revisão atual de Reels é `4ef6de98012d4484b35c962b42553b4f`, vinculada a `planning/2066aeda9513467e837359dec9666ff4`. |
| Construção de FFmpeg | `render.py:392-413` escolhe `_adaptive_camera_parts` para `adaptive_timeline`; usa `_static_camera_parts` para `full_frame_blur`. O caso estático em `:341` cria fundo desfocado e foreground amplo. Não foi encontrado um filtro que descarte decisões adaptativas nesses 16: elas não chegam porque o plano recebido já é amplo. |

## Por que os resumos do pacote não podem virar recortes por um alias

Nos 643 segmentos exportados, os campos são `director_id`, `start`, `end`, `layout`, `focus_person`, `camera_mode`, `zoom_mode`, `focus_confidence`, `zoom_start`, `zoom_end`, `safe_crop`, `upscale_ratio` e `reason_codes`. Há 555 `SOURCE_PRESERVE`, 63 `STATIC_CLOSE`, 24 `STATIC_MEDIUM` e 1 `SOURCE_FULL`.

Todos os 643 carecem de `camera.center_start/center_end`, `source_shot_id`, `crop.safe` e `camera_evidence_role`, exigidos em `camera_refinement.py:12` por `use_analyzer_director()`. Não seria seguro acrescentar `camera/candidate_camera_plans.json` como simples alias de `camera_timeline` em `evidence_source.py:47`.

`camera/camera_summary.json` declara `smart_zoom_enabled=true`, mas também `zoom_event_count=0`, `max_zoom_factor=1.0`, `zoom_delivery_verified=null` e aproximadamente 94,23% de foco não resolvido. A configuração habilitada não demonstra zoom entregue.

## Metadados canônicos existentes e a lacuna da GUI

Diretório existente: `../LDPORTO_VIDEO_ANALYZER/analysis/video_5198fcdaef38`. SHA256 da fonte: `b2958122415980a8afff4f77c23ead3c31c00345e5df0ab460995eb731efb00f`, igual ao projeto. Os hashes de quatro arquivos foram registrados em `canonical_camera_sources_before.json` antes de sua inspeção nesta auditoria:

- `analysis.json`: 64.952.083 bytes;
- `people_observations.json`: 35.600.556 bytes, 11.244 observações;
- `camera_director_timeline.json`: 1.866.385 bytes, 672 intervalos, dos quais 88 declaram `crop.safe=true`;
- `scenes.json`: 135.997 bytes, 432 cenas.

Há três comportamentos distintos na GUI:

1. `series_review.py:417` apenas guarda `canonical_path` e informa que a fonte será usada na **próxima importação**. Não enriquece o projeto aberto.
2. `_import()` em `:241-251` chama `load_evidence(..., canonical_dir=...)`, mas `_import_stories()` em `:256-275` usa o snapshot já carregado; `_resume()` em `:280-289` apenas reabre arquivos persistidos.
3. `SeriesProject.create_stories()` em `series_workflow.py:543-565` calcula a identidade por fonte/plano editorial/workflow; ao encontrar um projeto existente, preserva seu snapshot. Reimportar a mesma proposta não migra sua câmera nem suas evidências.

O snapshot atual não contém `provenance.canonical_source_sha256`. Isso prova que não há enriquecimento canônico persistido; não permite afirmar se o usuário clicou ou não no seletor.

Há também incompatibilidade objetiva no carregador genérico: `_directory_files()` em `evidence_source.py:89-105` enumera todo o diretório e limita os arquivos elegíveis a 256 MiB. Neste diretório há 612 arquivos elegíveis somando **1.908.411.364 bytes**, incluindo cache e `execution_inputs`. O carregador ultrapassa o limite antes de carregar somente as coleções necessárias. Além disso, o estado é `partial`, sem `completion.json`, `ANALYSIS_COMPLETE.flag` ou `COMPLETED.flag`. O adaptador não consulta `manifest.json` como comprovação de finalização; só considera `SECOND_CURATION_MANIFEST.json` nesse ramo. Não foi executada importação genérica de quase 2 GB nesta auditoria.

Não se recomenda aumentar o limite indiscriminadamente nem classificar todo `partial` como concluído. Uma operação seletiva precisa verificar fonte, checksums do `manifest.json`, ausência de etapas ativas e o estado das coleções consumidas.

## Segundo bloqueio: cobertura global versus decisão por intervalo

`use_analyzer_director()` exige, por padrão, 80% de cobertura segura do episódio inteiro (`camera_refinement.py:33-35`). A consulta dos 16 intervalos ao Director canônico retorna `None` para todos, embora alguns contenham pequenos intervalos com certificados válidos. O mínimo global elimina junto os intervalos bons e os intervalos que deveriam continuar amplos.

O caso só se corrige por nova operação explícita: manter todos os requisitos individuais de `valid()`, aceitar segmentos certificados no seu próprio intervalo e preencher lacunas com preservação da fonte. O parâmetro `minimum_coverage=0.0` já permite avaliar essa composição sem remover os requisitos individuais, mas seu uso precisa permanecer restrito a uma nova revisão e passar pelos controles de gráficos, dwell e geometria. Não foi alterado o padrão global, nem foi aplicado esse caminho ao fluxo normal.

Não há garantia de recorte para todos os Stories. Os caches locais de Reels têm cobertura integral de apenas seis janelas de Story, cobertura parcial de duas e nenhuma cobertura de oito. Além disso, observações canônicas contêm caixas reais do corpo: não se deve descartá-las para facilitar zoom. Por exemplo, a amostra em `358.566541...` tem caixa corporal de largura normalizada `0.5653`, maior que a largura `0.3164` de um recorte 9:16 na fonte 1920×1080. `camera_geometry.subject_box()` em `:25-37` conserva ombros e parte do tronco, podendo rejeitar esse recorte de forma correta.

## Correção mínima preparada, sem aplicação

`PATCH_PROPOSTO_NAO_APLICADO.diff` acrescenta ao CLI existente `scripts/REFINAR_CAMERA_EXISTENTE.py` um manifesto explícito de vínculos por episódio. Mantém o modo de um episódio e adiciona:

- dry-run que mostra decisões por intervalo sem criar revisão;
- verificação do hash do `series_index.json` pai, SHA256 da fonte e hashes dos dois arquivos de evidência por vínculo;
- rejeição de IDs duplicados/desconhecidos e da mistura de modos de seleção;
- preservação explícita por `preserve_without_visual_evidence=true` para episódios sem evidência segura;
- uma única chamada existente a `derive_camera_revision()` para criar cópia separada, reabrindo a aprovação;
- renderização só com `--apply --render-preview --source`, nunca no dry-run.

O manifesto é `LDP_STORIES_CAMERA_BINDINGS_V1`, com `source_sha256`, `project_index_sha256` e `episodes`. Cada item com evidência contém `episode_id`, `micro`, `metadata_project`, `micro_sha256` e `source_plan_sha256`. Caminhos relativos são resolvidos em relação ao manifesto. Um item sem evidência contém `episode_id` e `preserve_without_visual_evidence=true`.

Esse patch trata vínculos de micropercepção existentes, não promete converter resumos de candidatos ou ler metadados canônicos. O leitor seletivo canônico e a operação correspondente na GUI estão detalhados abaixo e ficam para a fase autorizada após aprovação das demonstrações. O código atual de produção permanece intacto.

## Integração canônica proposta para a fase seguinte

1. Criar leitor seletivo que leia somente `manifest.json`, identificação da fonte e coleções de câmera necessárias; rejeitar sentinelas/etapas ativas, divergência de fonte/duração/checksum e links. Preservar o rótulo `partial` e as limitações da associação de identidade.
2. Converter apenas os contratos completos do Director e observações existentes. Manter `bbox_kind=body`, ombros, mãos e sharpness medidos. Não criar geometria a partir de textos, nomes, resumos ou configurações.
3. Compor intervalos seguros certificados com lacunas amplas; gráficos sem certificado de recomposição mantêm fonte ampla. Zoom adicional exige as observações e a proteção de `smart_composition`, sem atribuir identidade pela presença de uma face.
4. Expor operação explícita de **nova revisão de câmera com evidência existente** na GUI, separada do seletor de próxima importação. Criar outro diretório e chamar a infraestrutura de revisão de câmera. Retomar/renderizar continuam sem replanejamento implícito.
5. Manter IDs, títulos, ordem, janelas, oito Reels e 16 prévias históricas; copiar os assets canônicos de legenda e título por SHA256. Produzir novas prévias e nova aprovação; não aprovar automaticamente.

## Validação necessária

O patch preparado deve ser aplicado somente após aprovação do usuário e dos testes da fase seguinte. A sintaxe foi validada e testes isolados do carregamento de vínculos ficam registrados no relatório de validação do patch. Não se devem somar esses testes da proposta aos testes do código instalado.

Para o leitor canônico futuro: testar fonte/checksums divergentes, `partial` estável versus etapa ativa, referências fora do diretório/links, resumos sem certificados, mistura mapa/apresentador com lacunas, recorte corporal impossível, período certificado menor que 80%, dwell mínimo, gráficos sem revisão e ausência de observações para zoom. Verificar a sobrevivência byte a byte de legendas, títulos, planos e MP4 históricos, inclusive Story 6. Verificar que reabrir/aprovar/renderizar um projeto não chama detector, ASR, CURAR ou replanejamento.

Referências de testes já existentes: `tests/test_safe_camera_maps.py`, `tests/test_camera_final_refinement.py`, `tests/test_camera_metadata.py`, `tests/test_camera_only_revision.py`, `tests/test_camera_transitions.py` e `tests/test_story06_camera_revision_p0.py`.
