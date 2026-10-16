# Auditoria de GUI, configuração, inicialização e documentação

Data: 16/10/2026. Escopo: leitura dos módulos de interface, configuração, timeline, player, ETA, entradas, dependências e classificação de documentação/scripts. Não foram abertos modelos, a janela gráfica, reprodução ou renderizações. Não houve alterações de produção nesta auditoria.

As medidas e o grafo de imports estão em [GUI_PERFORMANCE_EVIDENCIAS.json](GUI_PERFORMANCE_EVIDENCIAS.json). As linhas abaixo correspondem ao código encontrado antes das alterações globais desta fase; não são referências a cópias de backup.

## Resultado e limites

A abertura já possui duas proteções úteis: `gui.Pipeline()` importa o pipeline sob demanda e a consulta de estado usa debounce e thread de trabalho. Não há evidência de carga de Qwen, OpenCV ou NumPy ao importar a GUI. Os bloqueios restantes mais claros estão na retomada da janela V5, na consulta da GPU para ETA e na varredura de limpeza feita pela interface.

O diretório `output` foi encontrado vazio nesta sessão. O carregamento do projeto histórico e a leitura/hash da mídia original não puderam ser medidos. A construção de `SeriesProject` sobre um caminho ausente devolve plano/evidência vazios por usar `load_json(...,{})`; essa chamada é somente leitura. Nenhum sucesso de retomada real ou preservação de MP4 foi inferido desse resultado. A ausência dos arquivos requer conciliação antes de migração de projetos reais.

## Medições de inicialização

Cinco subprocessos novos por módulo, Python da `.venv`, flag `-B`, `perf_counter` em torno do import. As medidas não incluem criação de `Tk()`, construção de widgets, compositor do Windows ou carregamento de um projeto. O cache de disco pode estar aquecido. Nenhum arquivo `.pyc` foi escrito.

| Módulo | Mediana do import | Dependências pesadas já carregadas |
| --- | ---: | --- |
| `ldporto_curator.gui` | 45,6 ms | nenhuma entre cv2/NumPy/Torch/requests/Pillow/Pipeline |
| `ldporto_curator.series_review` | 51,7 ms | nenhuma entre as mesmas dependências |
| `ldporto_curator.pipeline` | 160,2 ms | requests, Pillow; sem cv2/NumPy/Torch |
| `ldporto_curator.local_player` | 26,6 ms | nenhuma entre as mesmas dependências |
| `ldporto_curator.timeline_editor` | 26,9 ms | nenhuma entre as mesmas dependências |

Primeira chamada de `eta.gpu_profile`: **49,8 ms**, GPU NVIDIA GeForce RTX 5070, driver 610.60. Esta execução foi rápida; o limite de espera do código é 5 segundos e a chamada ocorre na thread gráfica. Não há fundamento para atribuir congelamentos históricos a imports com base apenas nestas medições.

Reprodução mínima das medidas, sem abrir janela:

```powershell
.venv\Scripts\python.exe -B -c "import time; t=time.perf_counter(); import ldporto_curator.gui; print(time.perf_counter()-t)"
.venv\Scripts\python.exe -B -c "from ldporto_curator.eta import gpu_profile; import time; t=time.perf_counter(); print(gpu_profile()); print(time.perf_counter()-t)"
```

## Inventário e uso comprovado

| Arquivo | Responsabilidade e caminho de uso |
| --- | --- |
| `app.py:1–3` | Entrada gráfica; importa `gui.launch` e passa a raiz resolvida. |
| `gui.py:10–13,30–57,459–537` | Janela principal; Pipeline lazy, workers, fila e token por operação. |
| `series_review.py:58–70,230–277` | Janela V5.2, tarefas em worker, player, timeline, aprovação e retomada de revisões. Aberta por `gui.py:548–553`. |
| `local_player.py:13–110` | Decodificação OpenCV sob demanda em worker, fila de dois frames; FFplay separado para áudio. Usado pela revisão. |
| `timeline_editor.py:14–64,67–171` | Geometria de tempo canônico, snap, zoom, pan e seleção visual. Não processa mídia. |
| `crop_editor.py:270–493` | Editor manual sobre frames fornecidos; importado por fluxos/testes de edição. Não abre mídia nem executa detector por iniciativa própria. |
| `eta.py:15–76` | Perfil da GPU com cache e histórico de até 50 amostras compatíveis. Chamado pelo consumo de eventos da GUI. |
| `config.py:5–13` | YAML e normalização de três caminhos. |
| `storage_dialog.py:6–50` | Preview de limpeza, confirmação e execução explícita. Aberto pela janela principal. |
| `utils.py:6–14` | Leitura JSON tolerante e gravação direta; amplamente compartilhadas. |
| `import_smoke.py:22–43` | Inspeção/importação sem modelos/render; hash antes/depois do pacote. |
| `source_video.py:17–46` | Resolve override/local/nome no Analyzer/cache; exige hash da fonte; download exige opção explícita. |
| `director_config.py:24–53` | Validação dos estilos e limites de Smart Zoom; não é um segundo carregador global YAML. |

Não foram encontrados módulos dedicados chamados `session` ou `bootstrap`: a sessão está em `gui.py:357–383`, e o bootstrap está nos BATs/`app.py`.

O grafo estático percorreu os 57 módulos Python de produção, incluindo imports locais. Encontrou um ciclo: `camera_revision → series_workflow → camera_revision`. Os dois lados relevantes são imports dentro de funções (`camera_revision.py:18`; `series_workflow.py:323`), portanto o ciclo não impede o import e não justifica remover módulos. Nenhum ciclo eager foi demonstrado nas entradas auditadas.

## Achados com evidência

| ID / prioridade | Evidência | Causa e impacto | Correção incremental proposta |
| --- | --- | --- | --- |
| GUI-01 / P1 | `config.py:10`; `gui.py:73–79,454–457` | Somente analysis/output/source_cache são resolvidos; a GUI oferece análise e saída, sem separar mídia/estado. Os novos vídeos continuam sob o mesmo destino dos metadados. | Resolver pasta Vídeos pelo sistema, oferecer destinos separados e preservar o significado histórico de `output_root`. |
| GUI-02 / P1 | `episode_approval.py:28–39`; `persisted_plan.py:114–125` | Stories assinam o `cfg` inteiro, incluindo caminhos; Reels assinam uma projeção que exclui localizações. Alterar paths em `cfg` pode invalidar assinaturas históricas dos Stories, mesmo com bytes idênticos. | Manter configurações congeladas, separar resolução de localização do contrato histórico e não reescrever recibos/aprovações. Testar retomada com origem/cópia verificadas. |
| GUI-03 / P2 | `series_review.py:318–337`; `_load_review_project:20–55` | Retomar chama carregamento na thread Tk. A recuperação do Story 6 verifica fonte, evidências suplementares, assets e ASS canônico, podendo bloquear a janela. | Capturar valores Tk e executar a função em `_task`; devolver o projeto e a fonte pela fila. Não reduzir validações. |
| GUI-04 / P2 | `gui.py:215–218`; `eta.py:35–39,15–26` | Consumo de evento chama `gpu_profile()`/`nvidia-smi` na Tk; limite de 5s. `platform.processor()` também roda ali. | Obter perfil em worker antes da emissão do contexto; manter perfil/ETA compatíveis e resultado vazio explícito em falha. |
| GUI-05 / P2 | `storage_dialog.py:22–49`; `storage.py:174–209` | O diálogo percorre diretório inteiro, faz stat e hashes de scratch elegível dentro do callback síncrono; listas são materializadas. | Varredura em worker, progresso e cancelamento somente da consulta; executar exclusão apenas após preview confirmado e nova validação. Não ampliar candidatos. |
| GUI-06 / P2 | `gui.py:292–351`; `series_review.py:246–277` | Drenam a fila até ficar vazia, sem limite por rodada; log Text cresce indefinidamente. Flood de progresso/log pode monopolizar Tk e memória. | Limitar eventos por tick e coalescer progresso; preservar log integral fora do widget em destino configurado. |
| GUI-07 / P2 | `gui.py:537`; `pipeline.py:38`; `render.py:20–42` | Janela principal usa thread daemon sem cancelamento nem protocolo de fechamento; render de Reels não recebe cancel. Fechar janela pode interromper tarefa e deixar processo FFmpeg separado. | Encerramento cooperativo, cancelamento por token e espera pela finalização segura. Não encerrar processos desconhecidos e não apagar trabalho parcial. |
| GUI-08 / P2 | `local_player.py:43–87`; `series_review.py:635–643` | Cada seek cria nova thread/VideoCapture; sessão descarta frames antigos, mas não limita o número de decodificadores enquanto `open/read` antigos não retornam. | Debounce do seek e worker único por player, último pedido vence; manter fila limitada. |
| GUI-09 / P2 | `series_review.py:645–665` | Waveform usa `subprocess.run(timeout=45)`, sem cancel ao fechar; `waveform_busy` impede pedido novo e não reagenda o episódio mais recente. Falhas são silenciadas. | Token por fonte/janela, cancelamento do processo próprio, cache com chave de SHA/intervalo e erro visível sem bloquear revisão. |
| GUI-10 / P2 | `series_review.py:430–455`; `timeline_editor.py:122–154` | Seleção varre todos segmentos/cenas e abre/redimensiona capas na Tk; draw recria itens das lanes. Custo cresce com evidência/timeline. | Índice temporal e miniaturas previamente dimensionadas, cache limitado por assinatura; medir projeto grande antes de otimizar. |
| GUI-11 / P2 | `series_workflow.py:309–319`; `utils.py:6–10` | JSON ausente/corrompido vira `{}`; projeto inexistente pode aparecer como projeto vazio. Erro de parsing e arquivo faltante ficam indistinguíveis. | Validação explícita na entrada de retomada e erro legível; não alterar permissividade global de `load_json` sem testar todos consumidores. |
| GUI-12 / P2 | `cli.py:55`; `gui.py:518–525` | `--render-all` chama `Pipeline.render_all`; o botão normal chama `render_combined_batch`. CLI e GUI não entregam o mesmo lote Reels+Stories. | Explicitar CLI de lote combinado ou alinhar rota com teste de compatibilidade. Preservar comando legado se houver uso externo. |
| GUI-13 / P2 | `render.py:25–42`; contraste `series_workflow.py:234–272` | Runner de Reels lê stdout até EOF antes de drenar stderr; um stderr volumoso pode encher pipe e travar. Runner de Stories já drena ambos. | Compartilhar runner testado em revisão controlada. Alterar `render.py` muda fingerprint do renderer: não aplicar como ajuste de GUI sem conciliar aprovações. |
| GUI-14 / P3 | `gui.py:357–383,454–457` | Sessão salva apenas source/rank/output. Análise escolhida, mídia original, Ollama e novos destinos não persistem; falha de sessão é silenciosa na restauração. | Preferências próprias com esquema/versão, escrita atômica e fallback claro; não confundir com render_settings de revisões. |
| GUI-15 / P3 | `eta.py:72–75`; `gui.py:267` | A gravação do histórico ETA ocorre no consumo gráfico do evento de conclusão; `write_json` não é atômica. São no máximo 50 registros, portanto não há prova de gargalo atual. | Gravação pequena atômica em worker e deduplicação por operação; prioridade inferior a retomada/cleanup. |
| GUI-16 / P3 | `ABRIR_CURADOR.bat:11`; `INSTALAR.bat:19`; `requirements.txt:1–7` | Pré-checagem importa NumPy/requests sem necessidade para a GUI e não testa cv2/jsonschema; um ambiente parcialmente quebrado passa pelo bootstrap. `DIAGNOSTICO.py:5–7` só lista encoder, não valida NVENC em execução. | Verificar disponibilidade das distribuições sem import pesado e incluir dependências realmente usadas; distinguir encoder listado de encode homologado. |

`Pipeline.read_state` não é uma API puramente consultiva em todo estado: `pipeline.py:107–112,178–182` pode reconciliar `BATCH_RENDERING` interrompido; há lock, histórico e salvamento. Não foi chamado no benchmark para evitar escrita de metadados. Isso não demonstra exclusão de mídia ao abrir o programa, mas deve constar do contrato e dos testes de reinicialização.

## Caminhos configuráveis: proposta compatível

Não reutilizar `output_root` para significar Vídeos. É o local histórico de projetos/curation/índices, e suas referências precisam continuar válidas. Novo serviço de localização deve resolver artefatos por identidade e recibo, preservando o pacote de revisão inteiro quando seus manifests usam caminhos relativos.

| Campo proposto em preferências | Padrão / função |
| --- | --- |
| `analysis_root` | Valor atual do config, diretório concluído do Analyzer. |
| `original_media_root` | Opcional; busca limitada explicitamente escolhida, sem mover original. `source_media.path` continua sendo seleção exata validada. |
| `media_root` | Known Folder Videos do usuário + `LDPORTO_VIDEO_CURATOR`; resolver pelo SO, com fallback portável. |
| `projects_root` | Local atual de metadados; preservar `output_root` como contrato legado. O root pode decidir um alias migrado explicitamente. |
| `cache_root` | Diretório configurável para caches novos; não remover `.cache`/`source_cache` históricos. |
| `export_root` | Preferencialmente `media_root/exports` para pacotes/mídias exportadas; índices pequenos permanecem junto ao projeto. |
| `backup_root` | Fora da raiz do repositório, em local configurado; backups não são scratch. |

Recomenda-se preferências separadas de `cfg` assinado. A UI deve capturar e validar cada caminho na thread Tk, mas checagem de espaço, busca de mídia e migração devem rodar em worker. Exibir caminho efetivo após cada render e distinguir prévia/final, aprovação humana pendente e aprovação de publicação. Trocar destino nunca autoriza invalidar uma revisão antiga.

## Documentação e scripts: classificação segura

Na captura de `GUI_PERFORMANCE_EVIDENCIAS.json`, `docs` tinha **5.337 arquivos / 1.449.820.352 bytes**; `scripts`, **42 arquivos / 537.339 bytes** (inclui caches existentes); `examples`, **1 arquivo / 44.844 bytes**; `.docs` não existe. A contagem é um snapshot enquanto outros relatórios desta auditoria eram criados, não o inventário inicial autoritativo.

Foram confirmados **32 grupos de texto byte a byte idêntico**, por SHA256. A maioria pertence a payloads de instaladores, snapshots de código, handoffs e evidências de execuções históricas. Equivalência de bytes não prova que a cópia pode ser removida: um ZIP/payload histórico precisa permanecer reproduzível.

Casos verificáveis:

- `docs/architecture/CAMERA_VERTICAL_SEGURA.md` é idêntico à cópia em `camera_final_package_20261015/update_package/payload/docs/architecture/`; é duplicação esperada de pacote, não documentação concorrente ativa.
- `docs/reports/ORGANIZACAO_PROJETO.md` repete em três locais de validação/pacote; SHA256 `53292c7fd3b14f991ecbac8d93a7fa442e91797809c11e4e3bb69f86d8e6cbf0`.
- `docs/reports/camera_final_20261015/demos_hd_final/apresentador/DEMO_APRESENTADOR_1080x1920.mp4` tem 20.130.838 bytes. Há 106 MP4 no conjunto docs/scripts/examples da captura; todos são candidatos a cópia externa verificada, mantendo proveniência e referências históricas.
- `scripts/render_camera_demos_hd.py:26–27` exige que o destino fique em `docs/reports`. Esse guard torna a documentação destino obrigatório de MP4s novos e deve ser revisto junto com a migração, sem permitir sobrescrita.
- `README.md:41–48` documenta apenas saídas sob `output`, e a sequência principal ainda descreve lote final sem o resumo de prévias de Stories. Atualizar após a implementação real do armazenamento externo, preservando a explicação dos estados.
- `docs/reports/WORD_EVIDENCE_SEG00163.json` é entrada funcional da recuperação lexical do Story 6, referenciada por produção/script; não é um JSON sintético descartável. Não mover sem atualizar/verificar esse contrato.

Uso de scripts foi pesquisado em produção, testes, scripts e arquivos de entrada da raiz; resultado completo no JSON. São comprovadamente usados/testados: builders e instaladores de câmera/legendas, `NOVAS_PREVIAS_STORIES_CAMERA`, `RECUPERAR_OUTPUT_LDPORTO`, `REPARAR_STORY06_SEM_QWEN`, `REVISAR_CAMERA_SEM_QWEN`, demos V5 e validadores referenciados. `REPARAR_STORY06_SEM_QWEN` é importado por `combined_batch`, portanto movê-lo para uma subpasta quebraria produção sem adaptação.

Sem referências fora de docs na busca: `capture_render_p0_ui`, `REFINAR_CAMERA_EXISTENTE`, `render_camera_demos_hd`, `RETOMAR_STORIES_RECUPERADOS` e alguns validadores. Isso **não comprova abandono**: são entradas manuais/históricas; classificá-las para revisão e manter wrappers se forem reorganizadas. Não houve exclusão, movimentação ou consolidação destrutiva.

## Entradas e dependências

Entradas principais: `ABRIR_CURADOR.bat → app.py → gui.launch`; `TESTAR_1_CORTE.bat → cli.py`; `DIAGNOSTICO.bat → DIAGNOSTICO.py`; `INSTALAR.bat` instala ambiente. `cli.py` e `DIAGNOSTICO.py` executam no topo, sem guard `__main__`, portanto importá-los como biblioteca provoca parsing/ações; não foram importados.

As 21 entradas Python com guard encontradas na captura, além das entradas sem guard acima, estão enumeradas no JSON. São ferramentas de embalagem, recuperação, demonstração e validação; não fazem parte do startup normal.

Dependências declaradas: PyYAML, requests, Pillow, NumPy, yt-dlp, OpenCV headless e jsonschema. Tkinter é componente da instalação Python, e FFmpeg/FFprobe/FFplay/Ollama são executáveis/serviços externos, não pacotes instalados pelo requirements. Torch não é requisito do Curator nesta configuração. Não houve instalação ou atualização de dependências.

## Próximas correções com risco controlado

1. Implementar resolução externa em módulo novo e preferências separadas; testar inexistência, links, colisões, assinatura histórica e reabertura antes de alterar rotas de produção.
2. Tornar retomada V5 e consulta de limpeza assíncronas, com payload de resultado explícito e sem chamadas Tk dentro de workers.
3. Limitar consumo de filas e oferecer progresso/cancelamento cooperativo, preservando processo de aprovação humana.
4. Depois de conciliar fingerprints, consolidar runners FFmpeg e cancelamento de lote; não tocar render/legendas apenas para reduzir duplicação estética.
5. Acrescentar índice de documentação ativa e catálogo histórico, sem mover os documentos que ainda são inputs funcionais.

Esta auditoria não implementou essas propostas e não as conta como testes aprovados. As correções aplicadas pela tarefa principal devem ser registradas separadamente, com evidências antes/depois e a lista de limitações da homologação real.
