# Contrato LDPORTO_CURATOR_READY_V1

Versão 1, 17/10/2026. Implementação: `ldporto_curator/production_contract.py`; schema do manifest: `schemas/curator_ready_v1.schema.json`. Este contrato transporta propostas editoriais e evidência existente. Um pacote nunca concede aprovação humana, nunca executa programas e nunca inicia CURAR, Qwen, Analyzer, ASR ou renderização durante a leitura.

## Três entradas reconhecidas

| Formato retornado | Identificador no ZIP | Validação |
| --- | --- | --- |
| `ANALYZER_NATIVE` | `SECOND_CURATION_MANIFEST.json` | Verificador nativo existente, precedido da inspeção segura de nomes/tipos/tamanhos do ZIP. |
| `EDITORIAL_HANDOFF` | `PROJECT_MANIFEST.json` | Contrato `ldporto.project_dossier`, `schema_version: "1.0"`, inventário integral e identidade da fonte/ZIP nativo interno. Também pode ser uma pasta. |
| `CURATOR_READY` | `manifest.json` | Contrato descrito neste documento, checksums integrais e validações editoriais, temporais e geométricas. |

Mais de um desses manifests na raiz é ambíguo e é rejeitado. Não existe conversão por adivinhação de arquivos desconhecidos.

`read_production_archive(path)` retorna `format`, `files` (nomes relativos → bytes), `manifest`, `metadata`, `package_sha256`, `path`, `title`, `human_approval: null` e `publication_ready: false`. READY também retorna `pieces` e `evidence`. Nenhum conteúdo é extraído por essa função.

`read_editorial_handoff(path, expected_source_sha256=None, expected_package_sha256=None)` verifica uma pasta sem alterá-la. Para essa entrada, `package_sha256` identifica os bytes de `PROJECT_MANIFEST.json`; `source_package_sha256` identifica o ZIP nativo original declarado por esse manifest. `expected_package_sha256` confere o vínculo com o ZIP original, não o hash do manifest externo.

## Limites de segurança

Até 5.000 entradas e 256 MiB descompactados por contêiner; ZIP em disco até 288 MiB; razão de compressão por membro até 200. Pastas também têm inventário limitado a 5.000 arquivos/256 MiB. Pacotes internos são inspecionados com os mesmos limites. Não são aceitos links, junctions, membros especiais/encriptados, caminhos absolutos, unidades Windows, `..`, nomes reservados, colisões por maiúsculas/minúsculas, barras invertidas ou nomes não canônicos.

Extensões admitidas são dados inertes: JSON/JSONL, Markdown/texto, SRT/ASS/VTT, JPEG/PNG/WebP, PDF, HTML, CSV, ZIP e SHA256. Scripts e executáveis, incluindo `.py`, `.ps1`, `.bat` e `.exe`, são rejeitados. HTML e ZIP são tratados como bytes e nunca executados. Na leitura dos documentos JSON de contrato, chaves duplicadas, NaN, Infinity e expoentes não finitos são rejeitados.

## Árvore READY

```text
manifest.json
checksums.sha256
media_reference.json
editorial_revision.json
evidence/evidence.json
REELS/REEL_001/
  editorial.json
  source_segments.json
  camera_timeline.json
  camera_keyframes.json
  safe_areas.json
  caption_plan.json
  title_overlay.json
  audio_plan.json
  thumbnail_plan.json
  visual_evidence_refs.json
STORIES/SERIE_001/
  series_manifest.json
  PARTE_01/
    editorial.json
    source_segments.json
    camera_timeline.json
    safe_areas.json
    caption_plan.json
    title_overlay.json
```

Reels exigem os dez documentos listados. Partes de Stories exigem os seis documentos mostrados; os quatro documentos adicionais de Reel podem acompanhar Stories e, quando presentes, são validados. Assets reais referenciados precisam estar no pacote e no inventário.

Manifest mínimo, com hashes ilustrativos que devem ser substituídos pelos hashes reais:

```json
{
  "contract": "LDPORTO_CURATOR_READY_V1",
  "version": 1,
  "source_sha256": "<64 hex minúsculos da mídia original>",
  "title": "Título declarado da fonte",
  "files": [
    {"path": "media_reference.json", "bytes": 123, "sha256": "<hash dos bytes exatos>"}
  ],
  "reels": [{"path": "REELS/REEL_001"}],
  "stories": [{"path": "STORIES/SERIE_001"}],
  "publication_ready": false
}
```

`files` declara **todos** os arquivos, exceto o próprio `manifest.json` e `checksums.sha256`. Não pode haver arquivos omitidos, duplicados ou com bytes/hashes divergentes. `checksums.sha256` declara todos os arquivos **incluindo `manifest.json`**, excluindo somente a si mesmo; usa linhas `SHA256␠␠caminho/relativo`. O schema permite até 500 pastas de Reel e 40 séries READY; isso não limita as propostas presentes nos formatos nativos.

`media_reference.json` exige `source_sha256`, `duration`, `width`, `height`, `fps`. Os quatro campos técnicos também podem ficar no objeto `technical`. Duração/FPS são finitos e positivos; dimensões são inteiros positivos. IDs e título são opcionais e só devem declarar valores conhecidos. Não se cria YouTube ID a partir do prefixo SHA.

`editorial_revision.json` exige:

```json
{"provider":"ChatGPT","state":"HUMAN_REVIEW_REQUIRED"}
```

O outro provider permitido é `manual_json`. Se houver `source_sha256`, ele deve coincidir com a fonte. Flags de aprovação humana/publicação afirmativas e registros de aprovação importados são rejeitados no manifest, revisão e documentos de peça. A aprovação é ação explícita posterior no fluxo existente, vinculada à prévia real e à assinatura atual.

## Evidência e intervalos de origem

`evidence/evidence.json` mantém a forma normalizada usada por `SeriesProject`: `source`, `segments`, `words` e, quando utilizados, `candidates`. `source.sha256`, duração e dimensões devem coincidir com `media_reference.json`. Segmentos possuem `segment_id`, `start`, `end` e transcrição literal `text`; palavras possuem `word_id`, `segment_id`, `word`, `start`, `end`. IDs são únicos e palavras devem caber no segmento declarado. Não há alinhamento inventado na importação.

`editorial.json` contém um ID seguro e único em `piece_id` (ou `episode_id`, `clip_id`, `candidate_id`), título e referências. `candidate_id`/`candidate_ids`, quando fornecidos, devem existir na evidência. Exemplo de `source_segments.json`:

```json
{"segments":[{"start":12.0,"end":22.0,"segment_ids":["SEG_001"]}]}
```

Esses tempos são segundos **absolutos da mídia original**. Referências de segmento devem existir e ter interseção com o intervalo. Pode-se declarar mais de um intervalo somente quando forem contíguos, ordenados, sem lacuna nem sobreposição. O renderizador instalado trabalha com um recorte contínuo; montagem descontínua é rejeitada com `UNSUPPORTED_SOURCE_EDIT`. Cada Story deve ficar em até 59,5 segundos, incluindo a margem de codificação.

`caption_plan.json` deve conservar IDs, palavras e timestamps fornecidos pela evidência; palavras não podem escapar do recorte. Mudanças em `word`, `text`, `start`, `end` ou `segment_id` de uma palavra referenciada são rejeitadas. Um estado de revisão, como `ALIGNMENT_REVIEW_REQUIRED`, continua pendente após a importação. A existência de JSON mecanicamente válido não comprova sincronismo auditivo.

## Câmera

`camera_timeline.json` usa tempos **relativos ao recorte**, coordenadas **normalizadas na fonte original** e cobertura integral. `timebase: "clip_relative"` e `coordinate_space: "normalized"` são os padrões definidos por esta versão. Recomenda-se declará-los explicitamente.

```json
{
  "timebase":"clip_relative",
  "coordinate_space":"normalized",
  "source_width":1920,
  "source_height":1080,
  "segments":[
    {"start":0,"end":6,"mode":"FULL_VERTICAL_9X16","center_x":0.52,"center_y":0.42,"zoom_start":1.0,"zoom_end":1.03,"zoom_transition_start":0,"zoom_transition_duration":6},
    {"start":6,"end":10,"mode":"SOURCE_FIT_BLUR"}
  ]
}
```

| Modo declarado | Modo do motor existente |
| --- | --- |
| `FULL_VERTICAL_9X16`, `MEDIUM_SHOT`, `INSTRUMENT_FOCUS`, `AUDIENCE_FOCUS`, `crop` | `crop` |
| `SOURCE_FIT_BLUR`, `SOURCE_PRESERVE`, `full_frame_blur` | `full_frame_blur` |
| `DUO_COMPOSITION`, `split_screen` | `split_screen` |

O nome de modo não comprova presença de pessoa, instrumento ou plateia; a evidência e a revisão precisam sustentar a escolha. Crop exige `center_x`/`center_y` medidos ou pares `center_x_start/end` e `center_y_start/end`. Não há centro automático inventado pelo leitor. Centros ficam em `[0,1]`; o plano resultante será executado pelo renderer existente e ainda requer avaliação visual da prévia. Split exige exatamente dois `split_centers_x` medidos.

Zoom estático fica entre `1` e `1.13`. Envelope animado `zoom_start`/`zoom_end` fica entre `1` e `1.05`, limite suportado pelo motor atual; atraso e duração precisam caber no intervalo. Lacunas, sobreposições e modos desconhecidos são rejeitados. Trechos sem crop seguro devem declarar explicitamente o modo amplo. Não se impõe zoom a todas as cenas.

`camera_keyframes.json` usa `{"keyframes":[{"time":0,"center_x":0.5,"center_y":0.4,"zoom":1.0}]}`: timestamps relativos, finitos, estritamente crescentes, dentro da peça. A execução utiliza os envelopes suportados presentes na timeline. A validação de keyframes não implica suporte a interpolação arbitrária adicional.

`safe_areas.json` aceita regiões normalizadas `x_start/x_end/y_start/y_end`, retângulos `x/y/width/height`, ou `bbox` com `bbox_format: "xyxy"` explícito. Retângulos invertidos ou fora da fonte são rejeitados. Essas áreas registram evidência/restrições e não inventam a posição de mãos, instrumentos ou texto.

## Títulos, áudio, miniaturas e assets

`title_overlay.json` guarda a proposta de título. `thumbnail_plan.json` guarda a proposta de miniatura. Assets indicados por `asset_path`, `asset_ref`, `image_path`, `font_path`, `music_path`, `file_ref`, `asset_refs` e `file_refs` precisam apontar a membros declarados do pacote; não podem apontar ao disco externo. `visual_evidence_refs.json` usa `{"refs":["VISUAL_EVIDENCE/frame_001.jpg"]}` ou objetos `{"path":"..."}`.

`audio_plan.json` aceita `{"mode":"original"}` (padrão) ou `{"mode":"normalize"}`. Referência de música exige asset existente; isso não concede direitos nem transforma automaticamente a proposta em configuração executável. A API de leitura não altera áudio. O fluxo de projeto usa os recursos já existentes de áudio/legendas/título e preserva o áudio original quando essa é a escolha do plano.

Campos não executáveis continuam como documentos de origem; a importação não promete implementar efeitos arbitrários, HTML, scripts, esquemas de câmera desconhecidos ou composição descontínua.

## Séries e revisão

`STORIES/SERIE_001/series_manifest.json`:

```json
{"series_id":"SERIE_001","parts":[{"path":"PARTE_01"},{"path":"PARTE_02"}]}
```

A ordem do array é a ordem da série. IDs de séries e peças não podem repetir. As pastas de parte são relativas à pasta de série, confinadas a `STORIES`. Uma peça bloqueada mantém evidência e motivo; não autoriza aprovação ou publicação e não deve impedir a revisão de outras peças independentes.

## Dossiê PDF

`export_production_dossier(project)` cria, dentro do projeto **externo**, `04_RELATORIOS/DOSSIE_SEGUNDA_CURADORIA_<hash>.pdf`. O nome é derivado dos bytes, exportações idênticas reutilizam o arquivo e alterações criam novo PDF sem sobrescrever os anteriores. A função não salva o plano, renderiza ou aprova.

O PDF é textual e pesquisável. Inclui identidade, hashes, janelas absolutas, transcrição literal dos segmentos intersectados, propostas de títulos, gates de legenda, referências visuais e plano de câmera/zoom. Até 12 JPEGs reais, até 48 MiB no total e 25 MiB por imagem, podem ser embutidos sem alteração após checagem de hash/tamanho e confinamento ao projeto. Outros assets aparecem como referências explícitas; contact sheets continuam identificadas como contact sheets.

ReportLab não estava instalado; o exportador usa PDF 1.4 com fonte padrão Helvetica/WinAnsi, sem dependência nova. Português é preservado. Caracteres fora de CP1252 são representados por `?`, contabilizados em `unicode_replacements` e declarados no PDF; o JSON UTF-8 original continua sendo a autoridade literal para esses caracteres. O retorno inclui `path`, `sha256`, `bytes`, `pages`, `searchable`, quantidades de frames/assets/imagens e essa limitação.

## Verificação executada

40 testes isolados passaram para os leitores e o PDF. Cobrem preservação de estado, hashes, ZIP inseguro, scripts/links, limites de recursos, corrupção, flags de aprovação, NaN/expoentes infinitos, fidelidade de palavras, intervalos, câmera, assets, PDF pesquisável, JPEG íntegro, não sobrescrita e idempotência. O ZIP Analyzer real de 173 arquivos e o handoff real de 1.773 arquivos também foram lidos e validados, sem extração, render ou alteração das fontes.
