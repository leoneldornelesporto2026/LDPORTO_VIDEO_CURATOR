# Organiza??o do projeto ? ETAPA 00

Data: 15/10/2026, America/Sao_Paulo. Etapa conclu?da antes de qualquer altera??o no motor de legendas.

## Resultado

Auditoria recursiva conclu?da com preserva??o integral. Nenhum arquivo preexistente foi movido, exclu?do ou editado; espa?o recuperado: **0 bytes**. A restri??o posterior do P0 (n?o limpar caches nem projetos) prevalece sobre as sugest?es gen?ricas de limpeza. N?o houve commit, push, execu??o de Qwen, download de m?dia ou reprocessamento do Analyzer.

Foram inventariados **10.077 arquivos**, totalizando **2.057.443.010 bytes**, sem os internos do Git e sem os pr?prios entreg?veis desta auditoria. `.venv` recebeu invent?rio de metadados; todos os demais arquivos receberam SHA256, incluindo os **1.188 arquivos protegidos** em `output/`, `.cache/` e `source_cache/`. H? **310 grupos de conte?do id?ntico**, preservados porque c?pias de evid?ncia, revis?es, fixtures e baselines n?o s?o descart?veis pela igualdade de bytes.

## Estrutura anterior e final

A estrutura existente j? separa `ldporto_curator/`, `tests/`, `scripts/`, `docs/`, `docs/reports/`, `docs/second_curation/`, `schemas/`, `examples/`, `output/` e `source_cache/`. A raiz mant?m inicializadores Windows, `app.py`, `cli.py`, `requirements.txt`, configura??o e documenta??o operacional. A estrutura final ? a mesma, acrescida somente deste relat?rio e de `docs/reports/organizacao_20261015/`. N?o foram criadas pastas vazias nem reorganizados checkpoints hist?ricos.

`PROGRESS_UI_V2_NOTES.md`, `LEIA_PATCH.txt`, `VALIDATION_REPORT.txt` e documenta??o operacional na raiz foram preservados. Aus?ncia de refer?ncia textual n?o comprova que um script ou documento esteja sem uso. Mov?-los agora exigiria alterar caminhos de distribui??o e evid?ncias hist?ricas sem benef?cio comprovado.

## Invent?rio, refer?ncias e depend?ncias

- [Invent?rio inicial e hashes](organizacao_20261015/inventory_before.json): ?rvore completa, tamanhos, datas, status inicial do Git e SHA256.
- [Hashes do c?digo inicial](organizacao_20261015/code_hashes_before.json): produ??o, testes e scripts, incluindo altera??es locais preexistentes.
- [Hashes dos arquivos protegidos](organizacao_20261015/protected_hashes_before.json): fonte em cache, projetos, revis?es, aprova??es, renders e caches.
- [Duplica??es por hash](organizacao_20261015/duplicate_hashes.json): igualdade comprovada, sem inferir descartabilidade.
- [Refer?ncias e imports](organizacao_20261015/reference_audit.json): ocorr?ncias textuais de caminho/nome e imports por AST. O m?todo pode produzir falsos positivos; nenhuma exclus?o foi baseada apenas nele.
- [Verifica??o posterior da estrutura](organizacao_20261015/inventory_after_stage00.json): exist?ncia, tamanho e mtime de cada arquivo original. A [revalida??o independente dos hashes protegidos](organizacao_20261015/protected_hashes_after.json) confirmou **1.188 de 1.188 originais id?nticos**, sem falhas, ap?s as altera??es P0.

As depend?ncias declaradas s?o PyYAML, requests, Pillow, numpy, yt-dlp, OpenCV e jsonschema. `pip check` passou. Os tr?s caminhos resolvidos por `load_config` existem: Analyzer/analysis externo, output local e source_cache local. Caminhos absolutos de fontes do Windows e de snapshots de diagn?stico s?o hist?ricos ou espec?ficos da plataforma; n?o foi comprovado defeito que justificasse alter?-los.

## Preserva??o e arquivos grandes

Todos os 16 Stories de 3 s?ries e 16 revis?es do projeto persistido puderam ser lidos sem salvar. As revis?es da segunda curadoria e os oito Reels existentes foram inventariados, sem alterar aprova??es ou renderiza??es. Os maiores arquivos t?m finalidade comprovada: m?dia local em cache (1.200.651.212 bytes), bibliotecas do ambiente, evid?ncia consolidada do projeto (46.682.340 bytes) e preview hist?rico de valida??o (27.628.967 bytes). Nada foi classificado como remov?vel com seguran?a.

A m?dia `source_cache/zd_wjssZ7mc.mp4` possui SHA256 `a662f54c8c82ad509041979834a9493aa51651d2307647c5b934d8a517b56384`, diferente do contrato do projeto. **Essa c?pia n?o pode ser aceita como fonte verificada.** A fonte correspondente foi localizada e verificada, somente para leitura, em `../LDPORTO_VIDEO_ANALYZER/input/youtube/zd_wjssZ7mc/zd_wjssZ7mc.mp4`, com SHA256 `b2958122415980a8afff4f77c23ead3c31c00345e5df0ab460995eb731efb00f`, igual ao contrato. N?o houve reparo silencioso nem substitui??o de m?dia.

## Valida??o e problemas preexistentes

[Valida??o inicial detalhada](organizacao_20261015/baseline_validation.json): Python 3.11; **99 arquivos compilados em mem?ria** sem `.pyc`; **55 m?dulos de produ??o importados** sem erro; `cli.py --help` e `pip check` passaram. A interface Tk foi constru?da oculta, atualizada e encerrada com sucesso; restaura??o de sess?o foi desativada somente nesse smoke para n?o disparar inspe??es do estado persistido. Isso confirma a constru??o da interface, sem alegar homologa??o de todos os fluxos.

Pytest completo inicial: **478 passaram, 1 ignorado, 3 falharam em 43,34 s**. Falhas j? presentes antes das altera??es:

1. `test_p0_gui.py` usa um mock da rota antiga para o bot?o de lote, enquanto as altera??es locais existentes usam `combined_batch`.
2. `test_p0_legacy_recovery.py` pressup?e `CHATGPT_HANDOFF.json` na raiz hist?rica, ausente no ambiente; existe uma c?pia dentro de revis?o. Nenhuma evid?ncia foi fabricada.
3. `test_windows_gui_workflows.py` exige somente oito presets, enquanto a implementa??o j? possui o nono preset de Stories.

A repeti??o completa p?s-auditoria, iniciada antes das altera??es de produ??o, confirmou **478 passaram, 1 ignorado e as mesmas 3 falhas em 45,76 s**, registradas em `organizacao_20261015/pytest_after_stage00.xml`. A organiza??o n?o introduziu altera??o de c?digo.

Ap?s o encerramento da ETAPA 00, na continua??o P0, foram ajustadas somente as premissas dos testes: mock da rota `combined_batch`, presen?a do nono preset `story_upto_60` e fixture que exige todos os arquivos originais da auditoria hist?rica. O teste de assinatura arquivada continua executado; somente verifica??es dependentes dos originais ausentes s?o ignoradas, com motivo expl?cito. Valida??o direcionada: **61 passaram, 2 ignorados, 0 falhas em 1,95 s**. Nenhum arquivo hist?rico ausente foi fabricado ou restaurado automaticamente.

## Arquivos modificados e pend?ncias

Altera??es preexistentes preservadas: `ldporto_curator/final_camera.py`, `gui.py`, `story_import.py`; arquivos ainda n?o rastreados `combined_batch.py`, `smart_composition.py`, `scripts/REVISAR_CAMERA_SEM_QWEN.py` e `tests/test_smart_composition.py`. Os hashes iniciais os incluem.

Movidos: nenhum. Removidos: nenhum. Modificados pela organiza??o: nenhum arquivo preexistente. Criados: este relat?rio e artefatos de auditoria. N?o foi detectado import quebrado, erro de sintaxe ou depend?ncia instalada inconsistente. Duplica??o sem?ntica de l?gica n?o pode ser descartada por hashes e n?o justifica refatora??o nesta etapa.

Pend?ncias: avaliar documenta??o operacional hist?rica em manuten??o futura; declarar ambiente de testes separadamente se o projeto adotar instala??o reproduz?vel de desenvolvimento; executar a regress?o geral ap?s as altera??es P0; a integridade dos originais protegidos foi novamente comprovada por SHA256 ao concluir as altera??es P0. Qualquer limpeza futura deve preservar os arquivos associados a revis?es, mesmo quando id?nticos.

## Integridade ap?s implementa??o P0

Verifica??o independente de SHA256: **1.188/1.188 arquivos originais protegidos permanecem id?nticos**, inclusive m?dia em cache, oito Reels, projetos, revis?es, aprova??es e evid?ncias. [Relat?rio completo](organizacao_20261015/protected_hashes_after.json). Os novos artefatos derivados s?o listados separadamente, sem substituir a compara??o dos originais.

As **sete altera??es locais preexistentes** tamb?m mant?m exatamente os hashes iniciais: [verifica??o](organizacao_20261015/preexisting_user_changes_after.json). O verificador `scripts/verify_caption_protected_hashes.py` somente l? as ?rvores protegidas e grava seu relat?rio dentro de `docs/reports`. N?o foi detectado escritor concorrente alterando arquivos originais.

## Encerramento P0

Após as correções, a suíte final passou com **555 testes aprovados, 2 ignorados e zero falhas** em 58,30 s. Os dois casos ignorados exigem arquivos históricos já ausentes na auditoria inicial. O resultado está em `organizacao_20261015/pytest_delivery_verified.xml`.

A descoberta dos testes foi limitada a `tests/` por `pytest.ini`, preservando as cópias históricas e os pacotes de entrega sem coletá-los como testes ativos. O instalador e o empacotador passaram nos 28 testes específicos. A fonte original e os 1.188 arquivos protegidos mantiveram seus hashes. Relatório consolidado: `captions_p0_20261015_v2/ENTREGA.md`.
