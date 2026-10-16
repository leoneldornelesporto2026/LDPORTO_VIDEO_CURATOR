# Legendas de Stories: timeline por palavras

O motor V5.2.2 usa a transcrição literal e os intervalos individuais existentes. O modo padrão é `reveal_mode="word"`, escolhido para não mostrar palavras futuras. Cada palavra possui um evento canônico com seu ID original. `word_highlight` altera somente a cor; não altera a segmentação. Fragmentos ASR de uma expressão, como `8` e `.500`, conservam seus próprios IDs, substrings e intervalos medidos.

`ldporto_curator.subtitle_presets.write_episode_subtitles` gera `CAPTIONS.ass`, `CAPTIONS.srt` e `SUBTITLE_SYNC.json` a partir dos mesmos eventos. O JSON mantém tempos originais e relativos sem arredondamento, referência SHA256 da transcrição, IDs, origem do alinhamento, precisão não calibrada e pendência de revisão humana do áudio. ASS e SRT arredondam somente na serialização, respectivamente a centésimos e milésimos de segundo.

O layout mede a fonte local em uma referência de 1080×1920 e aplica escala proporcional para 540×960. Uma legenda tem no máximo duas linhas, posição consistente e limites seguros. Texto que não cabe é registrado como bloqueado; não se autoriza um vídeo com palavras omitidas ou texto fora da área segura. Sem alinhamento íntegro, o fallback mantém o segmento literal e seus tempos conhecidos, registra o motivo e exige revisão. Não existe distribuição uniforme de tempos.

`reveal_mode="block"` é uma opção explícita para frases curtas; permite que palavras posteriores do bloco sejam exibidas desde a primeira. Esse modo não satisfaz a restrição literal de ausência de antecipação e não é usado na demonstração entregue.

## Revisões e aprovação

`SeriesProject.derive_caption_revision(destino)` cria um projeto separado, preserva o projeto de origem e copia títulos e capas cujos hashes coincidem com o registro histórico. IDs, ordem, cortes, transcrição, planos de câmera e duração dos títulos continuam iguais. A revisão guarda snapshots do plano original, hashes e configurações congeladas. Aprovações antigas ficam no histórico; a nova revisão exige sua própria avaliação humana.

Se um pacote antigo omitiu palavras já existentes no Analyzer, `word_evidence=manifesto` permite recuperar somente segmentos sem registros. O manifesto exige SHA256 dos quatro documentos de origem, identidade da mídia, vínculo dos IDs ao segmento e correspondência exata das palavras com o cache ASR original. A adição ocorre antes do congelamento e somente no projeto derivado; `evidence_enrichment` registra a procedência. Isso não executa ASR nem altera texto ou timestamps.

`prepare_caption_timeline(episode_id)` apenas prepara ASS/SRT/JSON. `render(..., preview=True)` usa essa timeline e a câmera congelada. A renderização final exige a aprovação explícita da prévia e reutiliza sua timeline canônica, com layout na resolução final. Alterações na transcrição, no motor, nas configurações ou nos assets são recusadas. Nenhuma dessas operações chama Qwen ou o Analyzer.

O caminho legado dos Reels continua em `subtitles.write_subtitles` → `render.render_clip` → `pipeline.Pipeline`. O caminho dos Stories é `SeriesProject.render` → `subtitle_presets.write_episode_subtitles` → `render._base_cmd`. A correção do motor V5 não modifica os arquivos ASS/SRT/MP4 históricos dos Reels.

## Reprodução local

Use o Python da `.venv`. O comando abaixo valida o SHA256 da fonte, cria uma revisão separada, renderiza somente a Parte 1, extrai dez pares de frames e prepara as legendas dos outros quinze episódios. Os diretórios de destino devem ser novos.

```powershell
.\.venv\Scripts\python.exe scripts/validate_story_captions_p0.py `
  --project output/projects/zd_wjssZ7mc/stories_30af3ad6a05923e2 `
  --source ../LDPORTO_VIDEO_ANALYZER/input/youtube/zd_wjssZ7mc/zd_wjssZ7mc.mp4 `
  --derived output/projects/zd_wjssZ7mc/captions_p0_nova_revisao `
  --report docs/reports/captions_p0_nova_validacao `
  --word-evidence docs/reports/WORD_EVIDENCE_SEG00163.json
```

Para revisar o projeto na interface, use **Retomar projeto** e selecione o novo `series_index.json`. A aprovação/publicação permanece pendente. O relatório HTML e o WAV ajudam na conferência, mas a correlação de áudio e os testes de FFmpeg não comprovam a fala de cada palavra.
