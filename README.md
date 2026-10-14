# L.D.PORTO VIDEO CURATOR & RENDERER — Fase 2

Consome os resultados do **L.D.PORTO VIDEO ANALYZER** e gera curadoria, câmera conservadora, legendas ASS, frames de thumbnail e renders verticais.

## Fluxo V5.1 aditivo

Abra **V5.1 · Séries, estilos e dossiê ChatGPT** para importar um ZIP verificado, criar propostas cronológicas ou melhores momentos (inclusive com shortlist vazia), escolher as oito durações, revisar episódios e exportar evidências. O fluxo V4.4 abaixo continua disponível.

Veja [primeiros passos no Windows](docs/reports/curator_v5/PRIMEIROS_PASSOS_WINDOWS.md), [diagnóstico e limitações](docs/reports/curator_v5/DIAGNOSTICO_ANTES_DEPOIS.md) e [checkpoint](docs/reports/curator_v5/CHECKPOINT.md).

```powershell
.\.venv\Scripts\python.exe cli.py pacote.zip --plan-series --mode SERIE_CRONOLOGICA --duration-preset auto_under_90
.\.venv\Scripts\python.exe cli.py pacote.zip --dossier-only
.\.venv\Scripts\python.exe scripts/demo_curator_v5.py
```

Nenhuma dessas ações executa modelos ou reanalisa a fonte. Diretórios devem estar concluídos; transcrição parcial permanece identificada. Preview e aprovação humana são etapas distintas. O dossiê textual inclui legendas/capas disponíveis e referências verificáveis dos MP4, sem embutir a mídia integral por padrão.

## Fluxo seguro recomendado

1. Rode `INSTALAR.bat` uma vez.
2. Ajuste `paths.analysis_root` em `config.yaml` para a pasta `analysis` do Analyzer.
3. Rode `ABRIR_CURADOR.bat`.
4. Cole a URL já analisada.
5. Clique **CURAR**.
6. Clique **TESTAR 1 CORTE** (rank 1 por padrão). Isto gera apenas um preview 540×960.
7. Assista ao MP4. **Nada em lote é liberado ainda.**
8. Se estiver bom, clique **APROVAR TESTE**.
9. Só então clique **RENDERIZAR TODOS** para 1080×1920.

O bloqueio do lote é intencional e controlado por `safety.require_first_test_approval_before_batch`.

## Primeiro teste desta análise

O arquivo `curation_overrides.json` contém uma curadoria humana opcional para o sample `wA1ipztt54c`, começando pelo corte sobre Rick peitar a gravadora pelo Charlie Brown Jr. Vídeos futuros usam a curadoria genérica quando não existir override.

## Saídas

- `output/curation/<video_id>/EDIT_DECISIONS.json`
- `output/curation/<video_id>/CHATGPT_HANDOFF.json`
- `output/curation/<video_id>/CURATION_BOARD.png`
- `output/curation/<video_id>/clips/CLIP_xxx/thumbnails/*`
- `output/renders/<video_id>/CLIP_xxx/CLIP_xxx_PREVIEW.mp4`
- após aprovação: `CLIP_xxx_FINAL.mp4`

## Observação sobre câmera

A análise de referência não possui diarização/active-speaker confiável. Por isso esta versão usa **crop conservador** baseado em posições visuais observadas. Ela não inventa quem está falando. O plano fica registrado no JSON para revisão e evolução posterior.

## FFmpeg/NVENC

O programa detecta `h264_nvenc`; se não estiver disponível usa `libx264` e registra isso no log.


## Progresso visual V2

A interface agora mostra progresso estruturado durante CURAR, TESTAR 1 CORTE e RENDERIZAR TODOS:

- barra geral da operação;
- barra da etapa atual;
- `Etapa X/Y` e quantas etapas ainda faltam;
- fluxo visual `✓ concluído / ▶ atual / ○ pendente`;
- tempo decorrido;
- ETA adaptativo da etapa e do total;
- progresso real do FFmpeg durante o encode do preview/final;
- progresso de geração das miniaturas e do lote corte a corte.

O ETA começa como `calculando...` e só passa a estimar depois que existe progresso suficiente.
# V4.4 — atualização integrada

Runtime oficial: Windows/Python 3.11.x; testes locais em 3.11.9.
Use **IMPORTAR SEGUNDA CURADORIA** para carregar o core ZIP e depois
`SECOND_CURATION_DECISIONS.json`. O catálogo completo fica disponível no cache;
decisões explícitas mantêm seus limites e identificam FIRST_PASS,
SECOND_CURATOR, MANUAL_OVERRIDE ou AI_SECOND_CURATOR.

**TESTAR 1 CORTE** refina a câmera com evidência do Analyzer ou micropercepção
local a 6 fps. Face dominante não identifica o locutor. Crop/split reservam
uma cópia inteira do GC; o verifier registra amostras do MP4. Revise o preview
e use **APROVAR TESTE** antes do lote. Alterações de plano/MP4 invalidam aprovação.

Mídia ausente oferece baixar novamente, selecionar original ou cancelar;
o SHA256 deve coincidir com a análise. A limpeza apresenta estimativa e exige
confirmação, preservando dados editoriais, pacotes, contact sheets e renders.
Os arquivos e flags existentes anteriores à V4.4 permanecem preservados.

## Feedback opcional V4.4

`schemas/performance_feedback.schema.json` descreve views, retenção, likes,
comentários, shares, completion rate, CTR e rótulos manuais. O helper
`ldporto_curator.feedback.record_observed_performance` registra somente valores
explicitamente fornecidos, valida o SHA256 da fonte e preserva desconhecidos
como null. Nenhuma coleta externa, treinamento ou aprovação de render é executada.
