# L.D.PORTO — SEGUNDA CURADORIA (PROPOSTA R1)

**Fonte:** VARIG 254 | EP. 977 — Analyzer 4.4.0

**SHA256 do vídeo original:** `b2958122415980a8afff4f77c23ead3c31c00345e5df0ab460995eb731efb00f`
**SHA256 do pacote Analyzer:** `bb41aa652a3225715311d8694b1b1a4900b5439a6fcdfbb6849597168ed3f251`

**IMPORTANTE:** shortlist oficial do Analyzer = 0; gate `P1_DEGRADED`; 116 palavras para verificação; nenhuma correção de áudio inventada; nenhuma prévia aprovada.

## Reels propostos para revisão (não aprovados)

- **#1 — SEM CONTATO POR VHF: E AGORA?** · `MOMENT_00005_0001` · `977.18–1009.26s` · score Analyzer 0.862; conferir áudio, começo/fim e visual.
- **#2 — POR QUE O RÁDIO NÃO ALCANÇAVA?** · `MOMENT_00004_0002` · `793.20–837.86s` · score Analyzer 0.859; conferir áudio, começo/fim e visual.
- **#3 — O TRECHO SEM AEROVIA** · `MOMENT_00002_0003` · `448.68–485.26s` · score Analyzer 0.859; conferir áudio, começo/fim e visual.
- **#4 — O CHECKLIST ANTES DO POUSO** · `MOMENT_00004_0004` · `855.96–887.22s` · score Analyzer 0.851; conferir áudio, começo/fim e visual.
- **#5 — A ROTA DO VOO 254** · `MOMENT_00002_0002` · `422.54–448.60s` · score Analyzer 0.749; conferir áudio, começo/fim e visual.
- **#6 — QUEM ESTAVA NO COMANDO?** · `MOMENT_00002_0000` · `358.54–384.76s` · score Analyzer 0.754; conferir áudio, começo/fim e visual.
- **#7 — O QUE A INVESTIGAÇÃO BUSCAVA?** · `MOMENT_00011_0003` · `2015.10–2045.00s` · score Analyzer 0.727; conferir áudio, começo/fim e visual.
- **#8 — O QUE O PAINEL INDICAVA?** · `MOMENT_00006_0001` · `1198.82–1242.50s` · score Analyzer 0.813; conferir áudio, começo/fim e visual.

## Séries narrativas propostas

### DO PLANO DE VOO À ROTA (3 partes provisórias)
- Parte 1: Introdução ao voo e informações sobre os pilotos — 358.54 a 384.76s — MOMENT_00002_0000
- Parte 2: Detalhes do voo e rota entre Brasília e Imperatriz — 422.54 a 448.60s — MOMENT_00002_0002
- Parte 3: Detalhes do voo entre Imperatriz e Marabá — 448.68 a 485.26s — MOMENT_00002_0003
### RADIONAVEGAÇÃO E COMUNICAÇÃO (5 partes provisórias)
- Parte 1: Problemas com o alcance das antenas na Amazônia e a antena de Tucuruí — 793.20 a 837.86s — MOMENT_00004_0002
- Parte 2: Checklist de procedimentos de aproximação e pouso — 855.96 a 887.22s — MOMENT_00004_0004
- Parte 3: Uso do rádio HF e tentativa de contato com Belém — 977.18 a 1009.26s — MOMENT_00005_0001
- Parte 4: Panificação eletrônica e confusão com a localização do avião — 1198.82 a 1242.50s — MOMENT_00006_0001
- Parte 5: Discussão sobre cartas de navegação e desacordo entre Zille e Garcês — 1242.84 a 1257.12s — MOMENT_00007_0000
### A EMERGÊNCIA E AS CONSEQUÊNCIAS (7 partes provisórias)
- Parte 1: Sintonização dos rádios navegadores — 1637.12 a 1648.52s — MOMENT_00009_0008
- Parte 2: Solicitação de fechamento de aeroportos — 1684.00 a 1693.14s — MOMENT_00009_0014
- Parte 3: Preparação para o pouso e ações dos pilotos — 1761.61 a 1842.30s — MOMENT_00010_0000
- Parte 4: Impacto com a floresta e danos ao avião — 1845.89 a 1888.67s — MOMENT_00010_0001
- Parte 5: Localização do sinal de emergência e busca pelos sobreviventes — 1974.20 a 1985.96s — MOMENT_00011_0001
- Parte 6: Resgate dos sobreviventes e número de vítimas — 1989.04 a 2014.80s — MOMENT_00011_0002
- Parte 7: Consequências legais para os pilotos e objetivo da investigação — 2015.10 a 2045.00s — MOMENT_00011_0003

**Os intervalos acima seguem a ordem de apresentação da fonte. Não há comprovação automatizada de narrativa completa ou cronologia factual.**

## Legendas, títulos, câmera e capas

- Conferir as 116 palavras com áudio da fonte; registrar antes/depois com word_id, nunca substituir por dedução.
- Título 5s sobre vídeo em movimento, fonte medida dentro de caixa, rejeitar overflow.
- Crop inteligente somente com evidência espacial; Active Speaker parcial => SOURCE_PRESERVE quando houver dúvida.
- Cinco timestamps por Reel sugeridos como pontos de extração; não existem cinco PNGs reais neste pacote porque o vídeo original não foi fornecido.
- Prévia humana obrigatória. Sem autorização de publicação.

## Como importar no Curator

1. Aplicar patch ao Curator usando o instalador seguro, sem sobrescrever projects/output/.
2. No Curator clicar **IMPORTAR SEGUNDA CURADORIA** e escolher o ZIP original do Analyzer (sem recompactar).
3. Importar **SECOND_CURATION_DECISIONS_zd_wjssZ7mc.json**; o programa produzirá propostas `needs_review`.
4. Conferir áudio/video source SHA antes de prévia; aplicar títulos e ajustes finais; aprovar manualmente.
5. Na janela V5.2 importar ZIP original e usar a série como ponto de partida, com `STORIES_SEQUENCIAIS_REVISAR.json` como roteiro de revisão (não é importação automática de séries).
