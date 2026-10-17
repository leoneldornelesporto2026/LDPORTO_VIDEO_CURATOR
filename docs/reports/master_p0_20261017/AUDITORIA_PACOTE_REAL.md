# Auditoria do pacote real — 17/10/2026

Auditoria de arquivos existentes, sem executar Analyzer, Qwen, ASR ou novos modelos de percepção. Esta auditoria não concede aprovação editorial, musical, de legenda ou publicação. Os resultados antigos permanecem protegidos pelo inventário e backup realizados pelo coordenador em `CODE_BEFORE.json`, `INPUTS_BEFORE.json` e `PROTECTED_BEFORE.json` desta pasta.

## Identidade e integridade

| Entrada | Identidade verificada |
| --- | --- |
| Fonte, SHA256 declarado no pacote/dossiê | `5d089e1825b396dafd6b5918274f3a785eb2d8be2f622497cb7d06fdd7b3b7ea` |
| ZIP nativo | `SECOND_CURATION_READY_5d089e1825b3_20261017_020701_253736_8b80a1.zip` |
| SHA256 do ZIP | `5e5af9a17897eb424972c4d722a818ce29ca1d75dfff5e2e96b525932872f0cb` |
| Dossiê | `C:/Users/leone/Videos/LDPORTO_VIDEO_ANALYZER/Projeto_audiovisual__5d089e1825b3__20261017T021624775842Z_4a0271` |
| SHA256 de PROJECT_MANIFEST.json | `5d0410f2e412010209f578479e4f86ccf037905d817a98e0f27a6ab707a3145d` |
| Fonte técnica | 5.840,094 s; 1920×1080; 24,000001369843545 fps; rotação 0 |

O ZIP fica em `C:/Users/leone/Documentos/Meus Projetos/LDPORTO_VIDEO_ANALYZER/pacotes_para_enviar/`. Tem 173 entradas, 12.613.051 bytes comprimidos e 116.119.475 bytes descomprimidos. As 172 entradas declaradas no manifesto, totalizando 116.057.312 bytes, tiveram tamanho e SHA256 conferidos; o arquivo restante é o próprio manifesto. Não foram encontradas colisões de nomes, referências de caminho inseguras ou links no ZIP.

O dossiê tem 1.773 arquivos e 217.704.548 bytes. Todos os 1.772 arquivos listados tiveram tamanho e SHA256 conferidos; o arquivo adicional é PROJECT_MANIFEST.json. A cópia do ZIP interno está vinculada pelo mesmo SHA256 do ZIP externo. Essa ligação é necessária para enriquecimento; somente compartilhar a fonte não autoriza combinar revisões editoriais diferentes.

`source/metadata.json` declara `source.type=local`, `filename=original.mp4`. Não declara ID do YouTube, URL nem título da fonte. `5d089e1825b3` é o prefixo do SHA usado como namespace, e não uma identificação provada do YouTube. O dossiê declara `video_id=null`, `source_metadata_title=null` e `source_video_included=false`. O nome de uma pasta da biblioteca de mídia também não comprova a identidade de uma plataforma.

As prévias técnicas posteriormente localizaram a mídia em `C:/Users/leone/Videos/LDPORTO_MEDIA_LIBRARY/9UCGZia2p1k/original.mp4`, com rehash completo igual ao SHA esperado. Esse fato estabelece a associação ao arquivo, sem acrescentar uma identificação editorial não declarada pelo pacote.

## Conteúdo efetivamente disponível

| Coleção | ZIP | Dossiê / observação |
| --- | ---: | --- |
| Propostas de Reels | 70 | As 70 são propostas; shortlist de 1 não elimina as demais |
| Sequências provisórias | 49 | 86 referências a unidades/partes, mantidas na ordem declarada |
| Story independente | 1 | Não confundir com as 49 sequências provisórias |
| Segmentos literais | 386 | 386; o dossiê acrescenta campos, não novos segmentos |
| Palavras | 2.382 | 2.614: mais 232 registros existentes, sem ASR novo |
| Aparições de pessoas | 63.989 | Corpo e rosto são campos distintos; amostragem visual |
| Tracks/tracklets | 10.458 | Persistência dentro de track, sem identidade civil confirmada |
| Intervalos do Director | 4.042 | 132 com `crop.safe=true`; certificado completo continua obrigatório |
| Imagens do ZIP | 12 | São contact sheets; metadados fornecem 72 amostras temporais, não 72 JPG individuais |
| Instrumentos medidos | 0 | Lista vazia; estado desconhecido, sem inferir ausência |
| Identidades revistas | 7 registros | Nomes/associações humanos não confirmados |

O `PROJECT_MANIFEST` usa `ldporto.project_dossier` 1.0. O manifesto nativo usa schema 1.0, second-curation schema 3.1, Analyzer 4.4.0 e build `R4.9-S4-TRACKING-FACIAL`. O estado da análise é parcial e o estado editorial é `READY_FOR_REVIEW`: isso indica disponibilidade para revisão, sem declarar transcrição completa ou aprovação. Cobertura de transcrição declarada: aproximadamente 16,92%.

O arquivo nativo `HANDOFF_MASTER.json` existe, schema r6.1; o `06_SEGUNDA_CURADORIA/HANDOFF_MASTER.json` do dossiê é um wrapper de referências, schema 1.0. Ambos precisam ser interpretados segundo seus próprios contratos.

Há uma referência efetivamente quebrada: `04_STORIES/series.json.story_visual_handoff_ref` aponta para `06_SEGUNDA_CURADORIA/SECOND_CURATION_READY.zip#social/story_visual_handoff.json`; esse membro não existe no ZIP. O arquivo completo `camera/camera_director_timeline.json` existe. Não foi criado um substituto imaginado para a referência ausente.

## Contratos e consumidores

| Etapa | Evidência / consumidor | Consequência |
| --- | --- | --- |
| ZIP nativo | `second_curation_import.py:read_package` | Manifesto, SHA e catálogo nativo continuam sendo lidos pelo importador existente |
| Entrada dos três formatos | `production_contract.py:read_production_archive`, `read_editorial_handoff` | Validação limitada, sem extrair em output nem conceder aprovação |
| Adaptação nativa existente | `evidence_source.py:341`, `load_evidence` | Reutilizada pelo novo adaptador quando há caminho do ZIP |
| Normalização comum | `production_evidence.py:243`, `normalise_production_evidence` | Retorna evidence, pieces, visual_index e summary; nenhum processamento de mídia |
| Fonte/dossiê | `_verified_handoff`, `_merge_literal` | Exige SHA da fonte, duração e SHA do pacote exato; duplicatas precisam ter texto, janela e campos comuns consistentes |
| Propostas | `production_evidence.py:136`, `_pieces` | Preserva 70 Reels, 49 séries/86 unidades e 1 Story independente; sem CURAR ou nova seleção |
| Geometria | `production_evidence.py`, normalização de aparições | `observed_at` vira tempo absoluto; body_bbox vira bbox_kind=body; face_bbox continua face_bbox |
| Contact sheets / tracks | `production_evidence.py`, frames e tracks do índice | Conserva referência, SHA e caminho verificado quando materializado; não transforma contact sheet em frame individual |
| Plano por peça | `production_evidence.py:393`, `build_piece_camera` | Reutiliza `use_analyzer_director` por intervalo; gaps continuam amplos |
| Movimento | `camera_refinement.py:12`, `use_analyzer_director` | Preserva endpoints de zoom, tempo original e envelope suave no bridge |
| Filtros reais | `render.py:98`, `render.py:125`, `_motion_crop_filter` | O renderer existente usa zoom_start/end; envelope animado é limitado a 1.05 |
| Áudio / legendas | `production_package.py:caption_preflight`, `ProductionProject._gate` | Bloqueio explícito do produtor permanece autoritativo; alinhamento mecânico não vale como escuta humana |

O leitor genérico antigo reconhecia o timeline de câmera, mas não reconhecia `people/person_appearances.json`, `people/person_tracks.json` nem os aliases comerciais/visuais deste pacote. Assim `load_evidence` retornava 0 aparições, cenas, frames, OCR e graphics enquanto os documentos permaneciam carregados. O novo índice torna essas coleções consumíveis sem alterar os motores de geometria e legenda.

`05_CAMERAS/camera_timeline.json` do dossiê é um **handoff compacto**, apesar do nome. Não carrega todos os campos `focus_person`, `focus_confidence` e `camera_evidence_role` do Director nativo. Aceitá-lo como alias prioritário substituiria os certificados por resumos. Esse alias foi retirado do conjunto de certificados; o handoff permanece disponível separadamente como recomendação não aprovada.

## Legendas, áudio e títulos

Os 70 candidatos nativos têm `karaoke_allowed=false`, `allowed_caption_mode=none`, `alignment_verified_word_count=0` e nenhuma categoria de áudio observada. Entre os candidatos há 68 `ALIGNMENT_REVIEW_REQUIRED` e 2 `AUDIO_REVIEW_REQUIRED`; o Story independente acrescenta outro registro de alinhamento pendente. Não houve escuta ou ASR novo. `audio/sound_events.json` tem lista vazia, `origin_verified=null`, `listening_required=true`. Não há classificação positiva que permita declarar trechos instrumentais ou sem fala a partir de lacunas.

No dossiê completo, `_align_words` passa estruturalmente em 386/386 segmentos; no ZIP selecionado passa em 330, com 23 incompletos e 33 sem timestamps de palavras. Isso não é comprovação fonética independente nem autorização para karaokê. As 232 palavras suplementares foram incorporadas somente após verificar a ligação do dossiê e a consistência de todos os IDs comuns. Texto e tempos fornecidos não foram inventados ou corrigidos.

Os títulos declarados, inclusive títulos nulos, variantes rejeitadas e pendências, permanecem dados de proposta. Nenhum nome, letra, título ou identidade foi completado por inferência. O preset amarelo→branco existente e os módulos do renderer de legendas não foram alterados por este agente. `audio_events`/`audio` positivos eventualmente fornecidos no formato CURATOR_READY permanecem literais para a validação de fonte e janela do gate, sem converter eventos ausentes em silêncio.

## Câmera e limites comprovados

Uma cobertura global mínima de 80% pode rejeitar uma peça inteira com poucos intervalos locais certificados. A adaptação nova separa os intervalos nos limites do Director e executa o mesmo validador existente em cada intervalo, sem afrouxar segurança individual. Foco, confiança, papel visual, plano de origem, layout e crop.safe continuam obrigatórios. Os gaps recebem composição ampla explícita; mapas/conteúdo protegido com evidência de risco continuam amplos.

O bridge anterior copiava `min(zoom_start,zoom_end)` para um zoom estático, descartando o movimento antes da construção do filtro. A correção pontual acrescenta zoom_start/end e envelope apenas quando suportados pelo renderer atual, mantendo a interpolação rotulada `smoothstep_between_certified_endpoints`. Os keyframes originais permanecem no índice para inspeção. Não se afirma replay exato de cada keyframe ou medição de mãos/instrumentos.

O cache real chega a zoom 1.1234615, enquanto o filtro animado instalado aceita até 1.05. Portanto o adaptador usa `ANALYZER_ZOOM_EXCEEDS_EXISTING_RENDERER_ENVELOPE` e volta ao amplo nesses intervalos, em vez de achatar ou ampliar o contrato do renderer silenciosamente. O primeiro zoom seguro `[1147.25,1149.99471875]` vai de 1.0 a 1.0201011; o seguinte termina em 1.0300370. Esses dois cabem no renderer instalado.

## Ensaios de prévia e verificação dos pixels

O script `scripts/validate_production_camera.py` usa `SeriesProject.render`, sem aprovar candidatos ou invocar o lote. Todas as mídias ficam em `C:/Users/leone/Videos/LDPORTO_VIDEO_CURATOR/technical_camera_validation/`. O preset existente `SEM_LEGENDA` não desenha eventos ASS; palavras/timestamps literais continuam no registro de auditoria. O áudio permanece original, sem normalização e sem música acrescentada. Nenhuma nova revisão de output ou arquivo histórico foi sobrescrito.

Janelas técnicas, medidas a partir dos artefatos existentes:

| Ensaio | Fonte absoluta | Origem dos limites |
| --- | --- | --- |
| D, alternância | 1147.62–1153.82 | onset WORD_0000140 até offset WORD_0000159 |
| E, ampla | 1393.98–1397.38 | limites de SEG_00041; dois planos originais preservados |
| F, zoom | 1147.25–1150.48409375 | limites consecutivos certificados do Director, dentro do teto animado 1.05 |

As primeiras mídias em `20261017T055605Z_f123bfc8` são um ensaio preservado, **não uma validação de zoom**. Foram renderizadas a partir do índice do primeiro protótipo `15cbff3ae70a2e5f64a0`, criado antes da retirada do alias compacto. A inspeção real revelou F amplo. SIFT/RANSAC, comparando o original ao MP4, encontrou 622 e 615 inliers, escala aproximada 0.2813 nos dois tempos e crescimento de apenas 0,022%; não sustenta zoom. Esse resultado impediu anunciar sucesso somente pelo nome do arquivo/plano.

Os frames e as tentativas de homografia desse ensaio estão em `PIXEL_PROOF_1e77c0cc/PIXEL_MEASUREMENTS.json`. Uma tentativa inicial de alinhamento e uma tentativa de reconstrução em memória interrompida também foram preservadas. A validação final usará o índice persistido da nova importação normal, conforme coordenação; não adotará um índice ad hoc apenas para produzir um resultado visual favorável.

## Testes e escopo das mudanças

Até esta etapa, 29 testes passaram em `tests/test_production_visual_evidence.py` e `tests/test_v44_micro_camera.py`, com basetemp exclusivo fora do repositório e cache do pytest desativado. Cobrem vínculo do dossiê, conflito literal, fonte divergente, preservação de propostas, units/partes, geometria real, dados ausentes, gaps, mapas protegidos, limite do renderer, movimento parcial, frame/contact-sheet distinction, tracks, eventos de áudio literais e ausência de escritas durante normalização.

Mudanças deste agente: novo `production_evidence.py`, correção do bridge de zoom em `camera_refinement.py`, novo `test_production_visual_evidence.py`, script de ensaio e este relatório. Não foram alterados por este agente os módulos de legendas, títulos, renderer FFmpeg, áudio, projetos antigos ou arquivos sob output. Os arquivos de integração/contrato e verificações globais ficam sob responsabilidade do coordenador e dos demais agentes. Não houve commit, push ou limpeza destrutiva.
