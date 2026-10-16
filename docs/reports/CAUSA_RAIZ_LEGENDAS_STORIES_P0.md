# Stories V5.2 — causa raiz e correção P0 das legendas

Data: 15/10/2026, America/Sao_Paulo. A ETAPA 00 foi encerrada antes das alterações de produção; inventário, integridade, decisões de preservação e validações estão em [ORGANIZACAO_PROJETO.md](ORGANIZACAO_PROJETO.md).

## Defeito reproduzido

O episódio `PROP_f654d728d26180f2fb0e5816`, S01, Parte 1/3, usa a janela original 358,54–384,76 s, com duração de 26,22 s. Seu projeto histórico é `output/projects/zd_wjssZ7mc/stories_30af3ad6a05923e2`; a prévia original permanece em `serie_s01/001_PROP_f654d728d26180f2fb0e5816/0129f0edd87d2ade/preview`.

O JSON histórico contém 71 palavras alinhadas em cinco segmentos. `alignment="word"` descrevia a disponibilidade desses dados, mas não garantia que os eventos exportados os utilizassem. O preset `LDP_CLEAN` desativa o destaque de palavras. Em `write_episode_subtitles`, a condição antiga `if not words or not selected["word_highlight"]` enviava o segmento inteiro para um único evento quando o destaque estava desativado. Por isso, havia apenas cinco eventos com `method="segment"`, inclusive 23 palavras durante 9,20 s. Desligar um efeito visual desligava também o uso da granularidade temporal.

O SRT era montado diretamente no laço dos segmentos, antes do agrupamento usado pelo ASS. Assim, mesmo o caminho com destaque poderia produzir exportações com grupos distintos. O layout antigo tentava acomodar frases inteiras, recorrendo a uma composição em bloco que podia exceder as duas linhas declaradas pelo preset. Alterar somente o arquivo ASS não corrigiria nenhuma dessas causas.

## Implementação de produção

| Arquivo e funções | Correção |
| --- | --- |
| `ldporto_curator/subtitle_presets.py`: `resolve_subtitle_preset`, `_align_words`, `_canonical_events`, `canonical_timeline_hash`, `_validate_frozen_timeline`, `write_episode_subtitles` | Uma única timeline canônica define os eventos do ASS e do SRT. O destaque é independente da segmentação. Os tempos são derivados das palavras originais, com arredondamento somente na exportação. A reutilização de uma timeline valida sua identidade e conteúdo. |
| `ldporto_curator/subtitle_presets.py`: `_caption_layout`, `_measured_wrap` e serialização ASS | A largura é medida com a fonte real; posição, margens e linhas são verificadas nas duas resoluções. Eventos impossíveis de acomodar são sinalizados e bloqueiam o encode, sem encolhimento ilimitado da fonte. |
| `ldporto_curator/series_workflow.py`: `derive_caption_revision`, `_verify_caption_revision`, `prepare_caption_timeline`, `signature`, `render` | A correção de material histórico cria um projeto derivado. Plano, transcrição, câmera e configurações ficam congelados; título e capas são copiados por hash. A prévia e o final consomem a mesma timeline. Preparar legendas não dispara renderização. |
| `ldporto_curator/episode_approval.py`: `episode_signature`, `renderer_fingerprint` e gates existentes | A assinatura inclui o conteúdo relevante da transcrição e o código do renderizador. A aprovação continua vinculada ao MP4 e aos assets efetivamente revisados. Nenhuma nova aprovação é criada pela correção. |

A inspeção raster também identificou a diferença entre o tamanho EM medido pelo Pillow e a interpretação de `Fontsize` pelo libass. `_caption_layout` conserva a medição da fonte e normaliza o tamanho enviado ao ASS pela soma de ascendente e descendente. Isso evita que uma legenda corretamente medida seja desenhada menor pelo renderizador. O JSON registra `ass_font_size` e a normalização aplicada; o tamanho medido e as proporções 540×960/1080×1920 permanecem explícitos.

## Comportamento escolhido para esta entrega

O usuário escolheu exibição **palavra por palavra, sem antecipação**, com ASS e SRT equivalentes. Para o episódio real, são 71 eventos não cumulativos, com os mesmos 71 `word_ids` em ordem. A recomendação inicial de blocos de duas a cinco palavras não foi usada como padrão desta demonstração. O modo de bloco continua separado e não autoriza inventar tempos.

Cada evento registra texto literal, IDs originais, segmento, início/fim no clipe e na fonte, referência da transcrição, origem/precisão do alinhamento e estado de revisão. Para uma palavra totalmente contida na janela, `start = source_start - episode.source_start` e `end = source_end - episode.source_start`. Pausas reais ficam sem legenda. O texto original não é reescrito.

Alinhamentos ausentes, incompletos, incompatíveis com o texto ou sobrepostos recebem diagnóstico explícito e fallback conservador. Não se distribuem palavras uniformemente no tempo. Quando o fallback não pode respeitar o limite visual, `renderable=false` impede o FFmpeg de produzir uma prévia com legendas omitidas ou fora da área segura. A janela e a duração precisam coincidir; Stories acima de 60 s são recusados, sem corte automático de fala.

## Fonte, revisões e preservação

A fonte correspondente ao contrato foi localizada e revalidada por SHA256 em `../LDPORTO_VIDEO_ANALYZER/input/youtube/zd_wjssZ7mc/zd_wjssZ7mc.mp4`:

`b2958122415980a8afff4f77c23ead3c31c00345e5df0ab460995eb731efb00f`

A cópia existente em `source_cache/zd_wjssZ7mc.mp4` tem SHA256 diferente (`a662f54c8c82ad509041979834a9493aa51651d2307647c5b934d8a517b56384`) e não pode substituir a fonte contratada. Nenhuma das duas mídias foi modificada ou baixada novamente. O acesso ao original no diretório do Analyzer é somente de leitura; não houve nova análise.

A revisão final desta entrega fica em `output/projects/zd_wjssZ7mc/captions_p0_20261015_v2`. A primeira demonstração local fica preservada no diretório sem o sufixo `_v2`; os ajustes posteriores do motor exigiram uma nova revisão, porque o código do renderizador participa da assinatura congelada. O projeto histórico completo permanece preservado, inclusive suas revisões, 16 prévias, registros e hashes. Os oito Reels existentes permanecem nos diretórios originais, sem reencode. A nova revisão mantém as três séries, a ordem 3/5/8 de episódios, seus IDs, janelas, títulos de cinco segundos, ajustes de câmera e as cinco capas de cada episódio.

`caption_revision` contém os hashes do índice, evidência e manifesto do projeto de origem; cópias exatas desses documentos ficam em `parent_snapshot`. Assets históricos são conferidos contra `PREVIEW_REVIEW_V5.json`, e o MP4 antigo também é revalidado por SHA antes de derivar. Título e thumbnails são copiados com verificação de bytes. As referências de artefatos anteriores incluem o caminho do projeto de origem; os arquivos históricos não são sobrescritos.

O projeto derivado limpa somente seus gates ativos de prévia/final/aprovação. Uma prévia corrigida precisa ser assistida e aprovada explicitamente. Mudanças posteriores no motor, transcrição, câmera, decisões editoriais ou configurações exigem outra revisão. A exportação 1080×1920 reutiliza os eventos canônicos da prévia aprovada; a resolução altera apenas o layout. Não há chamada ao Qwen nesse fluxo.

## Recuperação de palavras existentes, sem nova transcrição

Os planos dos outros episódios revelaram duas condições distintas. Números e expressões como `8.500`, `1.112` e `terça-feira` estavam representados em fragmentos de palavras com tempos próprios. O motor 5.2.2 mapeia esses fragmentos para trechos literais contíguos, preservando todos os IDs e tempos, sem concluir incorretamente que faltava alinhamento.

No segmento `SEG_00163`, 972,12–977,04 s, faltavam efetivamente as palavras no pacote recebido pelo Curator. Uma consulta somente de leitura aos artefatos já existentes do Analyzer encontrou os 12 registros `WORD_0002445` a `WORD_0002456`, associados à hipótese `ASR_dbbc253ac4eba60d3e9322c0`. A sequência é exatamente “Vocês verem como a aviação no passado era bem mais tupiniquim, né?”, sem alteração do texto original do segmento.

[WORD_EVIDENCE_SEG00163.json](WORD_EVIDENCE_SEG00163.json) registra os caminhos e SHA256 dos quatro arquivos de comprovação. `manifest.json` declara o SHA256 contratado do vídeo e os arquivos de palavras/segmentos; `transcript_segments.json` atribui os 12 IDs ao segmento; `words.json` contém os registros completos; o chunk ASR `cache/b2958122415980a8/asr_chunks/b310c0cf6f6c7cf0_00004.json` declara a mesma identidade da fonte e contém os mesmos textos, hipótese e tempos medidos.

`derive_caption_revision(..., word_evidence=...)` revalida esses hashes e vínculos antes de criar o destino. A suplementação exige um segmento totalmente sem palavras no pacote original, literal e janela idênticos, IDs atribuídos pelo segmento do Analyzer, alinhamento integral e uma correspondência única de cada palavra no cache ASR original. Não substitui palavras existentes, não executa ASR nem inventa tempos.

Somente a cópia de evidência da revisão derivada recebe os 12 registros adicionais, antes de congelar seus fingerprints. Os segmentos originais e o campo editorial `episode.word_ids` permanecem iguais; `supplemental_word_ids` e `evidence_enrichment` registram separadamente o que foi recuperado. O projeto histórico e os arquivos do Analyzer permanecem inalterados. A origem é alinhamento Whisper já existente, com revisão humana do áudio ainda pendente.

## Evidências e revisão

Os artefatos finais desta execução ficam em [captions_p0_20261015_v2](captions_p0_20261015_v2/):

- `story_parte_1/PREVIEW_540x960.mp4`, `CAPTIONS.ass`, `CAPTIONS.srt` e `SUBTITLE_SYNC.json`: demonstração corrigida da Parte 1.
- `story_parte_1/frames/`: comparações antes/depois em 0,5; 1,5; 3,0; 5,5; 8,5; 10,0; 14,5; 19,0; 23,0 e 25,5 s.
- `story_parte_1/EVENT_SYNC_REPORT.json`: verificação dos eventos, texto, IDs e tolerâncias dos formatos.
- `story_parte_1/AUDIO_REVIEW.json` e `AUDIO_PARA_REVISAO.wav`: evidência para a conferência auditiva, sem afirmar reconhecimento independente da fala.
- `story_parte_1/resolution_1080x1920/`: exportação da mesma timeline para a resolução final, sem renderizar um final não aprovado.
- `outros_15/`: ASS, SRT e planos de sincronização dos outros episódios, preparados somente depois da demonstração da Parte 1, sem encode em lote.
- `DELIVERY.json` e `REVISAO.html`: caminhos, estados e página local para assistir e inspecionar.

O áudio permanece com estado `NEEDS_HUMAN_AUDIO_REVIEW` e `audiovisual_sync_homologated=false` até a conferência humana. Consistência dos timestamps, presença de áudio e sucesso do FFmpeg não comprovam, sozinhos, que cada palavra transcrita corresponde ao que foi pronunciado. Não foram feitas correções automáticas de nomes ou números.

Para retomar na interface, abra **V5.1 · Séries, estilos e dossiê ChatGPT**, escolha **Retomar projeto** e selecione `output/projects/zd_wjssZ7mc/captions_p0_20261015_v2/series_index.json`. Use **Selecionar mídia** para informar o original verificado no diretório do Analyzer. A interface passa sua configuração atual ao projeto; ela precisa coincidir com a configuração congelada. Pela API, `SeriesProject(caminho_do_projeto)` carrega automaticamente a configuração preservada. Não use **Novo plano com preferência global** para conferir esta revisão congelada.

Os testes novos em `tests/test_caption_revision.py` cobrem preservação de bytes históricos, cópia de título/capas, tampering de MP4/asset/timeline, mudança de transcrição/câmera/configuração/motor, teto de 60 s, ausência de encode na preparação, bloqueio de final sem aprovação e equivalência canônica entre prévia e final. A regressão do motor e a fixture real ficam nos testes de legendas. As contagens finais da execução completa são registradas junto aos resultados de validação da entrega.
