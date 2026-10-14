# Diagnóstico antes/depois — V5.1 aditiva

Inspeção local em 13/10/2026, Python 3.11.9. Este workspace não tem `.git`; `git status` e `git diff` não se aplicam. Baseline real: **37 testes passaram em 4,38s**. Hashes em `BASELINE_SHA256.json`; cópias dos arquivos legados editados em `baseline/`. O runtime do Curator foi reutilizado, sem instalar pacotes. Processos do Analyzer foram confirmados pela árvore de processos; nenhum arquivo/módulo/modelo/checkpoint/mídia dele foi acessado ou alterado durante a implementação.

| Área | Antes | Depois e limites reais |
|---|---|---|
| Legado | Curadoria V4.4, import bounded/decisions, overrides, câmera, preview e primeiro teste | APIs, configurações, BATs, contratos e testes preservados. Mensagens passam a dizer selecionados/revisão pendente; chave legada `approved_clips` mantida. |
| Evidências | Bundle e compact relevant segments | Adaptador ZIP/diretório concluído/decisões, inventário por componente, SHA256, versão/build mismatch e enriquecimento canônico explícito. Pacote parcial continua parcial. |
| Shortlist zero | Import podia gerar zero cortes | Propostas independentes de shortlist/decisões oficiais; catálogo e histórico não são aprovados nem promovidos. |
| História | Momentos independentes limitados no modo legado | Série dinâmica na ordem narrada, capítulos/arcs/Q&A presentes, mapa integral, cobertura por união de intervalos, lacunas e exclusões comerciais. Não infere cronologia histórica, acontecimentos ausentes ou payoff. |
| Duração | Limites legados 30–120s, até 12 cortes | Oito faixas exatas, Auto padrão, 900s inclusivo, milissegundos e override por episódio. Unidade indivisível sai com alerta; divisão semântica e reordenação mantêm origem e invalidam prévias afetadas. |
| Legendas | ASS/SRT legados | Presets locais, palavra real/gaps/clipping, fallback explícito por segmento, fonte real medida, zona segura, JSON de sincronismo. Nenhum timestamp de palavra inventado. |
| Câmera | Câmera V4.4 e micropercepção | Geometria existente reutilizada em modo conservador; source preserve padrão, risco de mapas/GC impede crop; keyframes manuais validados. Sem execução de detector/ASD/micropercepção/modelos nesta implementação. |
| Capas | Frames candidatos | Três PNG 1080×1920 com composições, título editável, fonte real integral, numeração, identidade e hashes. Timestamp é o seek solicitado; PTS exato do frame está `not_measured`. |
| Áudio/marca | Normalização legado | Voz original padrão; normalização opcional, trilha apontada com direitos explícitos, volume, ducking e PNG de marca textual. Fonte e trilha assinadas por hash. |
| GUI | Tkinter com botões originais | Janela aditiva com mapa, páginas de episódios, player/frame original/preview, seek, waveform, presets, edição, capas, gates, cancelamento e retomada. Controles avançados são JSON validados. |
| Aprovação | Primeiro teste V4.4 | Gate legado intacto; gate V5 por episódio vincula fonte/plano/config/renderer/FFmpeg/MP4/ASS/capa/trilha. Aprovação humana explícita; final não equivale a autorização de publicação. |
| Interoperabilidade | Handoff próximo dos cortes | Transcrição disponível integral, timestamps, contexto, cenas e dados ausentes, extras separados, propostas de copy DRAFT, visual assets e manifesto. MP4 integral não vai no ZIP textual; referência relativa/hash indica o que ficou externo. Arquivos auxiliares também são sanitizados. |

## Provas e limites

`demo_v2/DEMO_REPORT.json` aponta os artefatos atuais. Fixture declaradamente sintética: slides locais e narração SAPI instalada; sem Lito, sem Whisper/YOLO/Pyannote/Ollama, sem análise externa e sem publicação. A série tem duas partes na ordem; primeira prévia aproximadamente **27,322s**, som H.264/AAC 540×960, três capas e dossiê verificável. A demo registra **zero aprovações humanas** e não gera um final. Testes de integração temporários exercitam o final 1080×1920 mediante ação explícita de teste, sem homologar produto como humano.

Capturas reais da janela Tk no Windows: `GUI_MAPA.png`, `GUI_EDITOR.png`, `GUI_CAPAS.png`. Frames e FFprobe evidenciam decodificação/composição; não comprovam qualidade editorial nem sincronismo percebido por uma pessoa.

Pendências de produto/homologação:

- Conferência humana da narrativa, ASR, identidade dos speakers, payoff, spoilers, títulos, câmera, áudio, capas e direitos. O engine determinístico propõe a partir dos limites disponíveis; não oferece compreensão narrativa irrestrita nem pontuação viral nova.
- Homologação com o ZIP real do Lito depois da conclusão. A busca canônica é explícita para não acessar o Analyzer ativo; diretórios sem comprovante de conclusão são recusados.
- Player Tk/FFplay usa relógios separados; conferir sincronismo final no MP4 nativo. Não há garantia de sincronismo audiovisual fino no player embutido.
- A GUI não tem drag de boundaries, undo/redo visual, editor gráfico de crop nem galeria avançada de animações. Reordenação pelo número, limites numéricos, keyframes/estilos JSON e snapshots recuperáveis estão implementados.
- Não há importação de logo PNG fornecido, stems/remoção de música, CTA automático, VTT nem detector novo. O campo de marca suporta texto em PNG. Parâmetros de efeito inexistentes são rejeitados.
- Faixas longas até 900s têm testes de contratos/fronteiras/planejamento; o preview real de demonstração é curto e o final de integração também. Não foi executado um lote de episódios de 15 minutos em mídia real.

Esses limites permanecem explícitos: não declaro homologada toda a especificação P1 nem o material real. O código P0 e o fluxo P1 descrito acima são executáveis. A validação final e seus números estão em `VALIDACAO_FINAL.json` e `REGRESSAO_COMPLETA.txt`.
