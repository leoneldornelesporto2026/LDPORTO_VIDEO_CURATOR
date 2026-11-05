# Segunda curadoria — Charlie Brown Jr / Planeta Atlântida 2012

**Estado: PROPOSTA DE CORTE. Não é render nem aprovação de publicação.**

Pacote recebido: `SECOND_CURATION_PARTIAL_aUgESZsOGmY_20261020_021726_604899_b780c1.zip`.
O Analyzer 4.4.0 descreve **69 candidatos, shortlist oficial 0**, estado parcial e **nenhum áudio ou MP4 dentro do ZIP**. Existem imagens estáticas de referência, inclusive seis PDFs de atlas.

| Prioridade | Proposta | Início | Fim | Duração | Candidato |
|---|---|---|---|---|---|
| 1 | 20 anos de banda — seguimos evoluindo | 31:09.29 | 31:24.14 | 14,85 s | `MOMENT_00007_0001` |
| 2 | Gratidão da banda ao público gaúcho | 24:19.54 | 24:50.15 | 30,61 s | `MOMENT_00005_0000` |
| 3 | A energia da família Charlie Brown | 39:15.13 | 40:29.63 | 74,50 s | `MOMENT_00009_0001` |

As marcações são intervalos da **fonte**, não cortes renderizados. O terceiro une fala e passagem musical; não fazer cortes intermediários sem ouvir a continuidade. Segundo e terceiro têm risco de lacuna de contexto; a duração curta do primeiro é deliberada como teaser.

## Direção editorial

- **Formato-alvo:** 9:16 (1080×1920); primeira prévia 540×960.
- **Câmera:** `source_preserve` até validação visual real em movimento; não inferir identidade do cantor nem forçar crop/split.
- **Títulos:** limpos, curtos e fiéis ao conteúdo; evitar texto sobreposto a logomarcas ou rostos.
- **Legendas:** desativadas até alinhamento/revisão de fala. O Analyzer marca `ALIGNMENT_REVIEW_REQUIRED`.
- **Som:** manter áudio do show, aplicar cortes por pausas ou batidas *após escuta* e verificar volumes/ruído; não inventar falas.
- **Direitos:** autorizações de imagens e músicas não comprovadas.
- **Extras para avaliação:** interação com a multidão (35:52.16–36:39.40) e homenagem à banda (52:21.42–52:37.75).

## Arquivos

- `SECOND_CURATION_DECISIONS.json`: três ações `promote` compatíveis com o contrato V4.4; **nenhuma ação `approve`**.
- `EDITORIAL_CUT_PLAN.json`: evidências, riscos e etapas.
- `CUT_LIST.csv`: referência de timeline para revisão.

## Importar no Windows

Antes, localize o MP4 original correspondente ao SHA256 indicado. Na raiz do Curator:

```powershell
.\.venv\Scripts\python.exe cli.py "CAMINHO\SECOND_CURATION_PARTIAL_aUgESZsOGmY_20261020_021726_604899_b780c1.zip" --import-second-curation
.\.venv\Scripts\python.exe cli.py "docs\second_curation\aUgESZsOGmY\SECOND_CURATION_DECISIONS.json" --import-second-curation
```

O importador pode informar `approved_count`, mas seu próprio contrato marca `needs_review=true`: **a aprovação da prévia é outra etapa**. Não publicar automaticamente.

## Integridade

- SHA256 do pacote: `7dc84cf4f257578376c5aafb648139168cb94154475493222be8a22ef9605363`
- SHA256 do original exigido: `f8b424b9fc26c79141fb2288fee3354d5f02c1c773523f87f95b1191252283ea`
- Fonte: https://www.youtube.com/watch?v=aUgESZsOGmY

A `develop` contém uma alteração pontual de importação que aceita exclusivamente atlas `VISUAL_SCENES_ATLAS_NNN_NNN_MIN.pdf` de até 12 MiB, mantendo as validações de manifesto e hashes.
