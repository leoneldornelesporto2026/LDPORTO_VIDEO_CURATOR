# Primeiros passos — Curator V5.1

1. Aguarde o Analyzer terminar e fechar os arquivos do vídeo. Use o ZIP de segunda curadoria exportado; não selecione pastas com locks ou etapas ativas.
2. Abra `ABRIR_CURADOR.bat` e clique **V5.1 · Séries, estilos e dossiê ChatGPT**.
3. Escolha **SERIE_CRONOLOGICA**, **MELHORES_MOMENTOS** ou **COMBINADO**. **DOSSIER_ONLY** exporta as evidências sem cortes. O modo independente legado permanece nos botões originais.
4. O seletor começa em **Auto (<90s)**. As oito faixas estão disponíveis até **10m~15m**. Selecione **Importar ZIP**. Para enriquecer um ZIP parcial, escolha primeiro **Fonte canônica concluída**, com SHA256 correspondente, e importe novamente. Sem essa fonte, as lacunas continuam explícitas.
5. Em **Mapa e evidências**, confira disponibilidade, cobertura e lacunas. O inventário integral fica em `story_map.json`; a janela mostra os primeiros 100 blocos. Em **Episódios e estilos**, navegue pelas páginas de até 100 episódios.
6. **Selecionar mídia** aponta para o original analisado. O render confere seu SHA256. O original não é alterado nem baixado automaticamente.
7. Selecione um episódio. Veja os timestamps precisos, transcrição/contexto e cenas. Ajuste início/fim, título, número, faixa individual, legenda e câmera; clique **Salvar ajuste**. A divisão semântica preserva frases/Q&A e informa unidades que não cabem na faixa.
8. Use **Gerar preview + 3 capas**. Compare o original e o vertical no player; o slider busca o mesmo instante e a waveform representa o áudio do intervalo. **▶ Original** e **▶ Preview** reproduzem som por FFplay local; **Pausar** congela. Para conferir sincronismo rigoroso, assista também ao MP4 no player nativo do Windows: os relógios de Tk/FFplay são independentes.
9. Na aba **Capas**, escolha uma das três composições. Alterar a escolha requer outra prévia. Os JSON dos modelos e as imagens ficam na pasta do episódio. Título de publicação, título interno e texto de capa são campos separados.
10. Depois de assistir e conferir áudio, transcrição, câmera, legenda, capa e continuidade, clique **Aprovar preview assistido**. Propostas fora da faixa exigem aceitação explícita adicional. Mudanças de fonte, edição, estilo, capa, trilha ou renderer invalidam a aprovação afetada.
11. **Renderizar aprovados** gera somente episódios com prévia aprovada ainda válida, em 1080×1920 H.264/AAC, com SRT/ASS e validação FFprobe. Não libera publicação automaticamente.
12. **Exportar dossiê ChatGPT** salva pasta legível e ZIP verificável em `CHATGPT_HANDOFF` dentro do projeto. Envie o ZIP ao ChatGPT; leia `INDEX.md`, `evidence_availability.json` e `transcript/transcript_status.json` antes de escrever copy.

Projetos ficam em `output/projects/<video_id>/<revision>/`. **Retomar projeto** abre `series_index.json`. Preferência global cria outra revisão; edições preservam arquivos anteriores e snapshots em `revisions/`. Cancelar encerra somente o encode iniciado pelo Curator e mantém artefatos concluídos.

## Personalização disponível

O campo JSON de legenda aceita `font`, `font_size_final`, `color`, `highlight_color`, `outline`, `shadow`, `position_y`, `safe_zone`, `uppercase`, `animation` (`none`/`fade`), `max_words`, `max_chars` e `highlight_words`. Exemplo:

```json
{"font_size_final":72,"highlight_color":"#C5FF35","outline":5,"animation":"none"}
```

**Salvar modelo** e **Carregar modelo** mantêm presets locais. Sem alinhamento lexical suficiente, o sistema usa intervalo real de segmento, sem karaokê fictício. Blocos longos usam fontes legíveis e sinalizam sobreposição/overflow para revisão. Texto literal permanece nos arquivos.

**SOURCE_PRESERVE** é o padrão seguro. **AUTO_CONSERVADOR**, **FOCO_PESSOA** e **DOIS_PARTICIPANTES** dependem de geometria observada; mapas/textos/instrumentos ou evidências insuficientes levam ao fallback original. **MANUAL_KEYFRAMES** aceita, no campo próprio:

```json
[{"time":0,"x":0.5,"y":0.4,"zoom":1.0},{"time":5,"x":0.55,"y":0.4,"zoom":1.03}]
```

Tempos dos keyframes são relativos ao episódio. Bounds, zoom e velocidade são validados. Após dividir, os keyframes antigos precisam de remapeamento humano.

O campo de capa aceita `frame_times` (três timestamps absolutos), `layouts` (três presets), `show_part`, `brand` e `layout_overrides`. Exemplo:

```json
{"frame_times":[3,8,15],"layouts":["IMPACTO","DOCUMENTAL","MINIMALISTA"],"show_part":true}
```

Áudio começa em `{"mode":"original"}`. `{"mode":"normalize"}` ativa loudness. **Trilha própria** pede arquivo e confirmação de direitos, com volume/ducking ajustáveis no JSON. Não há remoção automática de música ou separação de stems. A marca textual opcional aceita:

```json
{"text":"l.d.porto.oficial","position":"bottom_left","opacity":0.75}
```

## Homologação manual pendente

Assista à fonte e às partes na ordem. Confira cortes de palavras, pergunta/resposta, continuidade, mapas/GC, rostos, tamanho das legendas, fala/áudio e títulos. Refaça uma prévia depois de alterar tempo/capa/estilo e confirme que a aprovação anterior não libera o final. O Lito não foi utilizado na demonstração; nenhum processamento completo foi iniciado.
