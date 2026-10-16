# Auditoria e organização — acabamento de câmera, 15/10/2026

A implementação parte do estado local existente, sem reset, commit, push ou
reimplementação. O Git já continha alterações de legendas, GUI, persistência e
recuperação. Elas foram copiadas antes da edição, inclusive arquivos não rastreados.

## Registros anteriores às alterações

- `git_status_before.txt` e `git_diff_before.patch`: estado inicial do Git.
- `code_before.json` e `backup_before/`: SHA256 e cópia de 133 arquivos de código,
  scripts, testes, configuração e README.
- `protected_before.json`: SHA256 de 1.016 arquivos em output, .cache e source_cache,
  totalizando 1.594.050.215 bytes. Nenhum link/junction foi percorrido.
- `source_before.json`: original do Lito, 213.166.733 bytes,
  SHA256 `b2958122415980a8afff4f77c23ead3c31c00345e5df0ab460995eb731efb00f`.
- `analyzer_evidence_before.json`: 487 arquivos externos JSON/JSONL/CSV/ASS/SRT do
  Analyzer, 1.897.161.113 bytes, inventariados somente para leitura.
- `structure_inventory.json` e `module_inventory.json`: estrutura, módulos,
  hashes e imports. O inventário estrutural foi consolidado depois do backup;
  os hashes anteriores às edições estão nos baselines específicos acima.

## Conciliação de uso simultâneo

Durante o trabalho, uma instância externa `app.py` estava aberta e produziu novos
renders e aprovações. O usuário confirmou que estava usando o Curator e informou
que fecharia o programa. Não foram revertidas essas ações.

`concurrent_activity_audit.json` registra sete arquivos de estado que mudaram e
nenhum arquivo inicial ausente. As mudanças incluem índices/playlist correntes,
STATE e painéis/handoff; não incluem perda de MP4 inicial. Foram encontrados 625
arquivos novos após o baseline inicial. A presença do aplicativo e a confirmação
do usuário explicam a necessidade de conciliar os baselines; não são uma atribuição
da causa do incidente anterior de output vazio.

Antes das correções finais, o estado resultante foi novamente inventariado em
`protected_reconciled_before.json`: 1.641 arquivos. Os índices foram copiados em
`concurrent_state_snapshot/`; código e testes receberam outro backup em
`before_final_validation/` e `code_before_final_validation.json`. A verificação
posterior `protected_reconciled_after.json` confirmou 1.641/1.641 hashes idênticos.
As 487 evidências externas do Analyzer e o vídeo original também permaneceram
idênticos. Esse resultado inclui os novos resultados gerados pelo usuário.

## Módulos e responsabilidades preservadas

| Área | Módulos principais |
| --- | --- |
| Câmera | camera, camera_evidence, camera_geometry, camera_motion, camera_refinement, smart_composition, final_camera, director_config |
| Metadados e revisão | camera_metadata e camera_revision; PlanStore e SeriesProject |
| Legendas | subtitles e subtitle_presets, derivados da timeline canônica |
| Títulos e identidade | title_card e title_presets |
| Render/exportação | render, media_effects, series_workflow, review, full_handoff |
| Aprovação/histórico | approval, episode_approval, persisted_plan, editing_history |
| Proteção/limpeza | storage e storage_dialog |

`camera.py` e `camera_refinement.py` têm consumidores diferentes; não são duplicatas
comprovadamente descartáveis. O mesmo vale para os dois adaptadores de legendas.
Não foram encontrados módulos de produção com conteúdo integralmente duplicado
no inventário por SHA256. As cópias em reports, fixtures, snapshots e pacotes são
evidências com função própria; igualdade de bytes não autoriza remoção.

As dependências declaradas continuam preservadas: PyYAML, requests, Pillow, numpy,
yt-dlp, OpenCV e jsonschema. Os imports foram inventariados e `pip check` passou.
Não foi comprovada dependência descartável. Não houve instalação/remoção de
dependências nem limpeza da .venv.

## Organização e candidatos futuros

Documentação técnica nova está em `docs/architecture/`; todos os relatórios,
comparativos, testes reais e backups desta atividade estão em
`docs/reports/camera_final_20261015/`. O pacote de atualização fica em diretório
separado, para não recopiá-lo recursivamente como evidência.

Arquivos históricos preservados na raiz: `PROGRESS_UI_V2_NOTES.md`,
`VALIDATION_REPORT.txt`, `LEIA_PATCH.txt`, `README_SEGUNDA_CURADORIA.txt` e manifests
de distribuição. Podem descrever etapas anteriores, mas não foi comprovado que
sejam inúteis. Os scripts `validate_v44_*`, `validate_render_p0.py`,
`REPARAR_STORY06_SEM_QWEN.py` e `RECUPERAR_OUTPUT_LDPORTO.py` também foram
preservados como ferramentas específicas de validação/recuperação. Alguns
pressupõem paths e nomes históricos; sua existência não autoriza execução em lote.

Não houve movimentação ou exclusão de documentos, módulos, dependências, caches,
originais, backups, projetos ou renders. Espaço liberado: zero. Arquivos incertos
continuam disponíveis para auditoria futura. Nenhuma limpeza destrutiva foi executada.

## Validação e limites

Os testes escrevem em diretórios exclusivos dentro de `%TEMP%`; as demonstrações
escrevem em novas revisões dentro de reports. Nenhum teste aprova um vídeo real.
As duas falhas iniciais de `test_karaoke_media_clock.py` foram reproduzidas com
o código do backup inicial em diretório isolado (`pytest_baseline_clock.xml`).
O teste antigo esperava ausência de `settb=AVTB` e comparava uma referência de seek
com relógio diferente. As premissas de referência foram corrigidas, mantendo
integralmente o motor de legendas e seu relógio já existente.

A causa do esvaziamento anterior de output segue indeterminada. A proteção atual
cobre as rotinas auditadas; não impede exclusões externas pelo sistema operacional.
Os resultados finais e as limitações visuais estão no relatório de entrega.
