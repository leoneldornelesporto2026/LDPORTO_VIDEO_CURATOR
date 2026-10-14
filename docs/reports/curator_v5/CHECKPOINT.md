# Checkpoint — Curator V5.1

Implementado neste workspace: adaptador de evidências e dossiê; story map/série dinâmica/shortlist zero; oito durações; divisão semântica e edição; presets ASS/SRT; câmera conservadora/keyframes; três capas; efeitos opcionais; gates por episódio; CLI e janela Tk aditivas.

Preservação: sem `.git`, sem commit, sem instalação e sem reprocessamento. Analyzer ativo não foi acessado. Hashes/cópias legados em `BASELINE_SHA256.json` e `baseline/`; outputs históricos e overrides mantidos.

Provas atuais: `VALIDACAO_FINAL.json`, `REGRESSAO_COMPLETA.txt`, `pytest_junit.xml`, `demo_v2/DEMO_REPORT.json`, `GUI_*.png`, `ARQUIVOS_E_HASHES.json`, `EXEMPLO_HANDOFF_CHATGPT.zip`. A demo é sintética, sem aprovação humana/publicação. Roteiro em `PRIMEIROS_PASSOS_WINDOWS.md`; limites em `DIAGNOSTICO_ANTES_DEPOIS.md`.

Reproduzir:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/demo_curator_v5.py
.\.venv\Scripts\python.exe scripts/capture_v5_ui.py
```

Próxima ação específica: quando o Analyzer terminar, abrir a janela V5.1, importar o ZIP concluído do Lito, verificar `evidence_availability.json` e selecionar apenas se necessário o diretório canônico concluído com SHA correspondente. Ouvir/assistir às propostas antes de aprovar cada preview. Não importar uma analysis ainda ativa nem converter a review queue em shortlist.

Para retomar desenvolvimento: implementar undo/redo visual e editor gráfico de crop sobre `SeriesProject.edit`/`reorder`/`split`, mantendo assinaturas e teste de invalidação; acrescentar testes reais de encode longo nas faixas 3–15m em amostra autorizada. Não alterar os gates para contornar lacunas.

Rollback de código: copie manualmente os arquivos pertinentes de `baseline/` para seus paths originais após revisar a comparação. Os módulos V5 novos são aditivos e podem permanecer sem uso; não remova outputs/ZIPs/overrides.
