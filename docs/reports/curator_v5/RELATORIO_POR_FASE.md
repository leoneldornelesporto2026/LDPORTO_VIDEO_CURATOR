# Relatório por fase — Curator V5.1

Regressão: 327 passed; 0 failures; 0 errors; 0 skipped; 21.15s.

Hashes por arquivo: `ARQUIVOS_E_HASHES.json`; comparação de legado: `PRESERVACAO_LEGADO.json`.

| Fase | Prioridade | Arquivos/artefatos | Evidência e risco |
|---|---|---|---|
| 0 — Auditoria/preservação | P0 | BASELINE_SHA256.json, baseline/, PRESERVACAO_LEGADO.json | 37 testes preexistentes; hashes originais; sem .git/instalação/Analyzer |
| 1 — Evidências/dossiê | P0 | evidence_source.py, full_handoff.py | Pacotes/snapshots íntegros; shortlist zero; transcrição parcial explícita; privado sanitizado |
| 2 — Story engine/durações | P0 | series_planner.py, duration_presets.py, series_plan_v5.schema.json | Série dinâmica; Q&A/frases; oito faixas; cobertura e divisão/reordenação |
| 3 — GUI/revisão | P1 | series_review.py, local_player.py, gui.py, cli.py | Tk real capturado; callbacks headless testados; avançados JSON; player sem sync fino garantido |
| 4 — Legendas/câmera/capas/áudio | P1 | subtitle_presets.py, title_presets.py, thumbnail_presets.py, media_effects.py, series_workflow.py | Frames e FFmpeg reais; regras de safe fallback; sem detecção/reanálise |
| 5 — Preview/gates/export | P1 | episode_approval.py, series_workflow.py | Prévia e final de integração; gates/hash/tamper; demo sem aprovação humana |
| 6 — Regressão/handoff | P0/P1 | VALIDACAO_FINAL.json, REGRESSAO_COMPLETA.txt, pytest_junit.xml, EXEMPLO_HANDOFF_CHATGPT.zip | Testes completos; ZIP CRC/SHA; humanos e Lito pendentes |

ZIP textual: EXEMPLO_HANDOFF_CHATGPT.zip, 552997 bytes, SHA256 `ab22873e1808ead3c6d63997bb8bfcedebb2cbdb117d3fe03924d4d7309c9acb`.
Preview real: `docs\reports\curator_v5\demo_v2\output\projects\curator_v5_synthetic_demo\4a6693803282\serie_01\001_PROP_aae5b058158b22933022af28\74781f1d14ddb2d2\preview\PREVIEW_540x960.mp4`; sequência de 2 partes; primeira gerada, restantes pendentes.

Nenhuma fase foi homologada editorialmente por uma pessoa. O material do Lito não foi usado. Limites de produto estão em DIAGNOSTICO_ANTES_DEPOIS.md.
