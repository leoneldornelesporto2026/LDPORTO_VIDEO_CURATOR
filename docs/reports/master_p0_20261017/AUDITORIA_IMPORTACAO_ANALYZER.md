# Importação Analyzer — MASTER P0, 17/10/2026

O importador de produção usa os motores existentes do Curator. Não executa CURAR, Analyzer, ASR, modelos de percepção, downloads ou aprovação. A entrada real foi importada em uma revisão externa nova, sem migrar projetos antigos.

## Evidências e matriz de compatibilidade

As matrizes detalhadas estão em [AUDITORIA_INTERFACE_FLUXO.md](AUDITORIA_INTERFACE_FLUXO.md), [AUDITORIA_PACOTE_REAL.md](AUDITORIA_PACOTE_REAL.md) e [AUDITORIA_PERSISTENCIA_IMPORTACAO.md](AUDITORIA_PERSISTENCIA_IMPORTACAO.md).

| Funcionalidade existente | Dado recebido | Consumidor | Limitação identificada | Ajuste realizado | Verificação |
| --- | --- | --- | --- | --- | --- |
| `read_package` / importação nativa | Manifest, metadados, catálogo e hashes | `production_contract` → leitor nativo existente | Entrada antiga exigia arquivos/configurações separados | Detecção de ANALYZER_NATIVE, EDITORIAL_HANDOFF e CURATOR_READY, validação antes de staging | Contratos sintéticos e ZIP real |
| FIRST_PASS / SECOND_CURATOR | Evidências e propostas importadas | Caminhos históricos mantidos | Executar nova curadoria mudaria seleção/identidade | Importação não chama esses motores | Regressão e flags de auditoria |
| `load_evidence` | Aparições, tracks, contact sheets, diretor e dossiê | `production_evidence` | Aliases reais não reconhecidos; coleções ficavam disponíveis no ZIP, mas ausentes do consumidor | Índice normalizado com proveniência, unidades, tempos e hashes | 63.989 aparições, 10.458 tracks, 72 amostras temporais |
| Camera Director / geometria existente | Certificados por intervalo | `build_piece_camera` → `use_analyzer_director` | Cobertura global descartava intervalos locais válidos | Plano completo relativo à peça, intervalos certificados e gaps amplos explícitos | Testes de cobertura e prévias D/E/F |
| Director completo versus handoff compacto | `camera/camera_director_timeline.json` e `05_CAMERAS/camera_timeline.json` | Índice persistido | O segundo é um resumo sem os certificados completos | Resumo não pode substituir o diretor certificado | Primeira tentativa falhou na medição; nova revisão corrigida comprovada |
| Filtro de zoom existente | Endpoints e envelope upstream | `camera_refinement` → filtros existentes → MP4 | O bridge reduzia os endpoints a um zoom estático | Endpoints preservados quando executáveis; movimentos acima de 1,05 recebem fallback explícito | Aumento de escala medido nos pixels do MP4 |
| ASS/SRT / karaokê existente | Palavras e segmentos literais | `caption_preflight` e writer existente | Alinhamento estrutural não comprova revisão fonética; erro isolado parava lote | Estados por peça, bloqueios upstream preservados, execução independente | Word, phrase, sem fala, instrumental e bloqueado em fixtures |
| Writer canônico de legendas | Evidência positiva de ausência de fala | `ProductionProject.prepare_caption_timeline` → serializer existente | Ausência de ASR não autoriza uma timeline vazia | Timeline vazia somente com cobertura positiva, SHA e IDs de eventos; sem palavras fictícias | MP4s reais de fixtures NO_SPEECH e INSTRUMENTAL |
| `SeriesProject` / renderer único | Reels e partes de Stories | `ProductionProject` delega render/approve/edit ao fluxo V5 | Janela contínua; montagem descontínua não implementada | Propostas preservadas; montagens incompatíveis ficam bloqueadas | Importação das 49 sequências e testes de descontinuidade |
| Revisões, undo/redo e aprovação | Propostas e alterações manuais | Histórico existente, locks e gates novos | Edição genérica descartava campos específicos de produção | Origem, gate e câmera preservados; alterações invalidam prévias conforme contrato existente | Edição/undo, concorrência e aprovação legada real |
| GUI V5.2 | Um ZIP | Mesmo SeriesReview, worker e resumo | Faltava entrada de produção e inspeção da câmera | Botão principal, resumo, timeline por trecho, editor de crop e comparação | GUI real com fixture READY e reabertura do projeto real |
| Exportação / dossiê | JSONs e imagens reais | `production_dossier` e exportador existente | Sem PDF editorial pesquisável | PDF externo, textual, com 12 JPEGs verificados e campos ausentes explícitos | 137 páginas, zero substituições Unicode neste caso |
| Armazenamento | Projeto novo e original existente | Known Folder Vídeos e biblioteca de mídia | Acúmulo histórico em docs/output | Novos projetos de produção externos; destinos internos recusados | Testes para output, docs, docs/reports e .cache |

## Resultado real e identidade

Fonte local, sem ID do YouTube declarado. O prefixo `5d089e1825b3` é um namespace do SHA256. O original foi integralmente rehashado e tecnicamente conferido em `C:/Users/leone/Videos/LDPORTO_MEDIA_LIBRARY/9UCGZia2p1k/original.mp4`; o nome dessa pasta não acrescenta uma identidade nominal ao pacote.

- Fonte SHA256: `5d089e1825b396dafd6b5918274f3a785eb2d8be2f622497cb7d06fdd7b3b7ea`.
- ZIP SHA256: `5e5af9a17897eb424972c4d722a818ce29ca1d75dfff5e2e96b525932872f0cb`.
- Revisão válida de integração: `C:/Users/leone/Videos/LDPORTO_VIDEO_CURATOR/Projeto_audiovisual__5d089e1825b3/revisions/63114d7dd8af829e4a40`.
- 70 propostas de Reels; 49 sequências/86 partes, mais 1 Story independente. Nenhuma é tratada como aprovação.
- 157 peças com pendências: 69 de alinhamento, 35 de áudio e 53 bloqueadas por montagem/duração/outros gates explícitos. Não foi disparado o lote.
- Os 1.774 arquivos de entrada inventariados mantiveram seus hashes. Os 805 arquivos anteriores em output/.cache/source_cache também permaneceram intactos.

A referência `social/story_visual_handoff.json` informada pelo dossiê não existe no ZIP. A lacuna está registrada; os dados reais existentes são usados sem fabricar esse documento.

## Limites de execução e revisão

O formato READY é um contrato de proposta, sujeito a revisão humana e compatibilidade do motor instalado. Não existe pacote real de segunda curadoria ChatGPT homologado nesta rodada; o teste READY é sintético. Não há evidência positiva de instrumental/ausência de fala no pacote real, nem geometria medida de mãos/instrumentos. O importador não inventa essas informações.

O editor conectado permite centro, zoom, limites, composição ampla, keyframes, posição de legenda e estilos já executados pelo V5. A posição do título continua a zona fixa do gerador atual; identidade nominal do alvo e criação interativa de novas regiões protegidas não ganharam controles executáveis nesta rodada. Documentos importados desses assuntos são conservados como propostas, e não representam suporte irrestrito a overlays, assets ou keyframes arbitrários. Montagens descontínuas e envelopes animados acima de 1,05 continuam incompatíveis.

Essas limitações impedem declarar homologação integral de produção ou conclusão de todos os controles P1. Os testes e MP4s comprovam a importação, persistência e execução da câmera delimitadas nos relatórios, sem substituir revisão audiovisual humana.
