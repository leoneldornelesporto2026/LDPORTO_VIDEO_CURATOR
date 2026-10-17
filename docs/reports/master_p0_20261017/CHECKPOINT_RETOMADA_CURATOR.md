# Retomada segura — MASTER P0

Data: 17/10/2026. O último anexo recebido é idêntico ao primeiro MASTER P0. Nenhum novo objetivo substituiu o trabalho em andamento.

## Estado concreto

- Projeto real importado: `C:/Users/leone/Videos/LDPORTO_VIDEO_CURATOR/Projeto_audiovisual__5d089e1825b3/revisions/63114d7dd8af829e4a40`.
- Original associado: `C:/Users/leone/Videos/LDPORTO_MEDIA_LIBRARY/9UCGZia2p1k/original.mp4`, SHA256 `5d089e1825b396dafd6b5918274f3a785eb2d8be2f622497cb7d06fdd7b3b7ea`.
- 70 Reels, 49 séries/86 partes e 1 Story avulso: propostas importadas, nenhuma aprovada. As 157 peças têm gates pendentes; não disparar lote para contornar essas pendências.
- Demonstrações válidas: `C:/Users/leone/Videos/LDPORTO_VIDEO_CURATOR/technical_camera_validation/20261017T130058Z_70e74423`. Não usar os ensaios antigos como evidência de zoom.
- PDF: ver `REAL_DOSSIER.json`; 137 páginas pesquisáveis, 12 imagens incorporadas, sem aprovação automática.
- Novo botão na GUI: **IMPORTAR PACOTE DE PRODUÇÃO**, na mesma tela de revisão V5.2. Para retomar o projeto real, abrir seu `series_index.json` pelo comando de retomada da revisão. Reabrir conserva cfg e evidências da revisão; não executar CURAR.

## Checkpoints

| Etapa | Estado demonstrado | Limite / próximo trabalho |
| --- | --- | --- |
| 01 diagnóstico | Matriz, ZIP e dossiê reais auditados, inventário e backup prévio | Referência ausente de story_visual_handoff registrada |
| 02 importação | Três formatos, segurança, staging/journal, mídia por SHA, revisão externa | Conciliação manual quando houver fontes/revisões ambíguas |
| 03 visual | Aparições, tracks, diretor, contact sheets, frames temporais e proveniência normalizados | Sem geometria real de mãos/instrumentos; sem identidade nominal inferida |
| 04 diretor | Plano por intervalo consumido pelo motor existente | Gaps amplos; certificados incompletos não viram autorização de crop |
| 05 zoom | MP4 real e crescimento medido de 1,9363% | Revisão visual de instrumento/ação ainda necessária; limite animado 1,05 |
| 06 legendas | Estados distintos, frase conservadora e ausência positiva de fala/instrumental testados | 70 candidatos reais continuam sem liberação de legenda pelo Analyzer |
| 07 Stories | Ordem e intervalos importados no mesmo fluxo de render/revisão | Montagem descontínua e partes acima de 59,5 s bloqueadas |
| 08 READY | Schema/contrato, referências/hashes, testes sintéticos e importação pela GUI | Nenhum pacote real ChatGPT homologado nesta rodada |
| 09 interface/armazenamento | Importação única, resumo, câmera por trecho, crop visual, reabertura e novos destinos externos | Posição livre de título, editor de região protegida e seleção visual de novo alvo ainda não concluídos |
| 10 homologação | Regressão, MP4s D/E/F, medição de pixels, reabertura real e SHA de legado | Aprovação audiovisual humana e revisão das legendas reais pendentes |

## Arquivos e limites que não podem ser perdidos na retomada

`production_contract.py`, `production_evidence.py`, `production_package.py` e `production_dossier.py` são adaptadores do fluxo existente. O Camera Director, o renderer FFmpeg, os presets amarelo→branco e o sistema de aprovação continuam sendo os motores atuais. Não criar renderer paralelo, aprovações artificiais ou palavras/timestamps inventados.

O gerador de títulos atual usa posição vertical 0,13. Um READY que exija outra posição é recusado explicitamente; não é reposicionado silenciosamente. Título/ativação/duração e opções de capa compatíveis são aplicados. Regiões protegidas declaradas no READY são confrontadas com a geometria do crop; incompatibilidade força amplo preservando a proposta original.

Não limpar output/cache/docs, não migrar arquivos antigos, não substituir referências históricas, não executar instaladores, commit ou push. Backup e rollback estão documentados em `AUDITORIA_OUTPUT_ORGANIZACAO.md`. Novos materiais pesados precisam ficar fora do repositório; os scripts históricos listados na auditoria ainda precisam de adaptação antes de novas demonstrações volumosas.

## Verificações

`FULL_TEST_RESULTS_FINAL.xml`: regressão final com **895 passados, 5 pulados, zero falha/erro**, em 94,14 s. `PRODUCTION_FINAL_TEST_RESULTS.xml`: 108 testes de produção, incluindo as proteções de regiões, títulos e todas as alterações posteriores. `FULL_TEST_RESULTS.xml` é a primeira regressão anterior (887 passados/5 pulados); não somar contagens de suites sobrepostas.

`PROTECTED_AFTER.json`, `LEGACY_APPROVAL_VERIFIED.json`, `GUI_REAL_REOPEN_SMOKE_FINAL.json`, `REAL_IMPORT_VERIFIED.json`, `REAL_PREVIEWS_VERIFIED.json` e `REAL_DOSSIER.json` são evidências leves. O MP4, os frames de prova e o PDF ficam somente em seus caminhos externos.
