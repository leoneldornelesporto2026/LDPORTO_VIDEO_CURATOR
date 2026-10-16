# Legendas dos Stories: o mesmo karaokê dos Reels

O padrão atual de novos Stories é `LDP_REELS_KARAOKE`: o bloco completo, normalmente com três a seis palavras, aparece em amarelo. Cada palavra muda para branco no seu início medido e permanece branca até a troca de bloco. A posição, as quebras de linha e a fonte permanecem fixas durante o bloco. O texto pode ser mostrado antes da fala; a mudança para branco nunca é antecipada.

Reels e Stories chamam o mesmo serializador `subtitles.measured_karaoke_body`. As mudanças de cor usam offsets absolutos das palavras, sem somar durações arredondadas. O estilo reproduz os oito Reels finais: Segoe UI em negrito, tamanho ASS 60 em 1080×1920, amarelo `#FFD700`, branco `#FFFFFF`, contorno escuro de 6 px, sombra de 2 px e margens laterais/inferior de 130/320 px. Em 540×960 as medidas são proporcionais.

A transcrição e os intervalos individuais continuam imutáveis. Fragmentos ASR de uma expressão, como `8` e `.500`, conservam seus próprios IDs e intervalos, permanecendo no mesmo bloco visual para não cortar a palavra. A exibição isolada `reveal_mode="word"` continua disponível apenas como opção de compatibilidade; ela não é o padrão do novo karaokê.

`ldporto_curator.subtitle_presets.write_episode_subtitles` gera `CAPTIONS.ass`, `CAPTIONS.srt` e `SUBTITLE_SYNC.json` a partir dos mesmos blocos canônicos. O ASS implementa as mudanças de cor dentro de um único evento por bloco; o SRT oferece o mesmo texto e os tempos dos blocos, sem cor. O JSON mantém tempos originais e relativos sem arredondamento, referência SHA256 da transcrição, IDs e cada transição de cor. A precisão auditiva continua não calibrada e pendente de conferência humana. O ajuste de tempo ocorre somente ao serializar os formatos.

O layout mede a fonte local em uma referência de 1080×1920 e aplica escala proporcional para 540×960. O perfil dos Reels conserva o tamanho ASS original; os perfis antigos preservam sua normalização anterior. Uma legenda tem no máximo duas linhas, posição consistente e limites seguros. Texto que não cabe é registrado como bloqueado. Sem alinhamento íntegro, o fallback mantém o segmento literal e seus tempos conhecidos, registra o motivo e exige revisão. Não existe distribuição uniforme de tempos.

As prévias e os projetos criados antes da correção deste requisito continuam preservados. Abrir um projeto existente não troca seu preset nem recalcula decisões. A migração usa uma nova revisão derivada com `subtitle_preset="LDP_REELS_KARAOKE"`; neste momento, somente a Parte 1 é renderizada para comparação antes de aplicar o novo estilo aos outros quinze Stories.

## Revisões e aprovação

`SeriesProject.derive_caption_revision(destino, episode_ids=[id], subtitle_preset="LDP_REELS_KARAOKE")` cria um projeto separado somente para o episódio selecionado. Preserva o projeto de origem e copia títulos e capas cujos hashes coincidem com o registro histórico. IDs, ordem, cortes, transcrição, planos de câmera e duração dos títulos continuam iguais. A revisão guarda snapshots do plano original, hashes, preset resolvido e configurações congeladas. Aprovações antigas ficam no histórico; a nova revisão exige sua própria avaliação humana.

Se um pacote antigo omitiu palavras já existentes no Analyzer, `word_evidence=manifesto` permite recuperar somente segmentos sem registros. O manifesto exige SHA256 dos quatro documentos de origem, identidade da mídia, vínculo dos IDs ao segmento e correspondência exata das palavras com o cache ASR original. A adição ocorre antes do congelamento e somente no projeto derivado; `evidence_enrichment` registra a procedência. Isso não executa ASR nem altera texto ou timestamps.

`prepare_caption_timeline(episode_id)` apenas prepara ASS/SRT/JSON. `render(..., preview=True)` usa essa timeline e a câmera congelada. A renderização final exige a aprovação explícita da prévia e reutiliza sua timeline canônica, com layout na resolução final. Alterações na transcrição, no motor, nas configurações ou nos assets são recusadas. Nenhuma dessas operações chama Qwen ou o Analyzer.

O caminho legado dos Reels continua em `subtitles.write_subtitles` → `render.render_clip` → `pipeline.Pipeline`. O caminho dos Stories é `SeriesProject.render` → `subtitle_presets.write_episode_subtitles` → `render._base_cmd`. A correção do motor V5 não modifica os arquivos ASS/SRT/MP4 históricos dos Reels.

## Reprodução local

Use o Python da `.venv`. O comando abaixo valida o SHA256 da fonte, cria uma revisão separada e renderiza somente a Parte 1 para comparar as cores e o comportamento dos blocos. O projeto de destino deve ser novo. Os outros quinze episódios não são preparados ou renderizados por esta operação.

```powershell
.\.venv\Scripts\python.exe scripts/validate_story_reel_karaoke.py `
  --project output/projects/zd_wjssZ7mc/stories_30af3ad6a05923e2 `
  --source ../LDPORTO_VIDEO_ANALYZER/input/youtube/zd_wjssZ7mc/zd_wjssZ7mc.mp4 `
  --derived output/projects/zd_wjssZ7mc/captions_p0_nova_revisao `
  --report docs/reports/stories_reel_karaoke_nova_validacao
```

Para revisar o projeto na interface, use **Retomar projeto** e selecione o novo `series_index.json`. A aprovação/publicação permanece pendente. O relatório HTML e o WAV ajudam na conferência, mas a correlação de áudio e os testes de FFmpeg não comprovam a fala de cada palavra.
