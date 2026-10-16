# P0 — diagnóstico de output deslocado, 16/10/2026

`output` está vazio nesta inspeção. Os conteúdos de `curation`, `projects` e `renders` foram encontrados na Lixeira em dois conjuntos distintos. **Os 964 arquivos de output da última entrega P0 verificada foram encontrados com o mesmo caminho original e SHA256 no conjunto anterior. Não há arquivo desse baseline ausente na união inspecionada.**

A Lixeira comprova o destino e os horários de reciclagem. Os registros consultados não identificam o processo ou a pessoa que realizou a operação. Não foi atribuída a causa ao usuário, ao Curator, ao Explorer ou ao VSCode.

## Eventos e conteúdos encontrados

| Evento em São Paulo | Evento UTC | Conteúdo | Arquivos | Bytes |
| --- | --- | --- | ---: | ---: |
| 08:44:47 | 11:44:47 | `curation` + `projects` + `renders`, geração anterior | 964 | 710.423.936 |
| 09:32:24.514 | 12:32:24.514 | `_BACKUP_STORIES_2PARTES_20261016_091314`, arquivo intencional informado pelo usuário | 68 | 64.096.119 |
| 09:33:20 | 12:33:20 | `curation` + `projects` + `renders`, geração mais recente | 1.055 | 882.836.917 |

Os índices `$I` contêm os caminhos originais, datas, tamanhos declarados e respectivos payloads `$R`. A lista completa com SHA256 está em [P0_REGISTROS_LIXEIRA_WORKSPACE.json](P0_REGISTROS_LIXEIRA_WORKSPACE.json). Para o último evento:

| Árvore original | Índice | Payload | Arquivos | Bytes |
| --- | --- | --- | ---: | ---: |
| `output/curation` | `$IX0I3Z7` | `$RX0I3Z7` | 406 | 121.636.277 |
| `output/projects` | `$IIEGRZ7` | `$RIEGRZ7` | 516 | 448.933.381 |
| `output/renders` | `$IN5O1OA` | `$RN5O1OA` | 133 | 312.267.259 |

O backup de duas partes tem plano `STORIES_3c5b7b1a5770306f843c15c3`. Ele permanece separado e não foi considerado projeto ativo ou substituto das três séries e 16 Stories.

## Integridade da última geração

[P0_OUTPUT_DESLOCADO_DIAGNOSTICO.json](P0_OUTPUT_DESLOCADO_DIAGNOSTICO.json) registra cada caminho original, sua tradução estrita para o payload correspondente e o SHA256 recalculado. Nenhuma referência persistida foi regravada.

- **8/8 Reels atuais e 16/16 prévias atuais dos Stories coincidem com os SHA256 persistidos.**
- A revisão atual dos Reels é `4489a2650087462ca459d23724415182`, em `BATCH_COMPLETED`, com oito resultados e registro de aprovação presente.
- `PlanStore.load(check_settings=False)` validou os hashes de `PLAN_INPUTS.json` e `ANALYSIS_SNAPSHOT.json` e os contratos das entradas imutáveis.
- Preview, approval record, recibos em disco, flag de aprovação, MP4 da prévia e sidecar coincidem. O vínculo da assinatura também coincide com o renderer atual. Os SHA256 de todos esses metadados estão listados no JSON.
- As 16 assinaturas de Stories foram reproduzidas com contextos exatos, sem alterar plano ou configuração persistida. Todos os assets referenciados coincidem com o inventário SHA256 das 1.055 entradas.
- O índice principal referencia 15 prévias; o Story 6 está na revisão independente `story06_caption_recovered_047cafe2e748`. A distribuição continua S01=3, S02=5, S03=8. **Nenhum Story possui aprovação humana.**

## Comparação com a entrega P0 anterior

Foi usado `docs/reports/story06_signature_p0_20261016/PROTECTED_AFTER.json`, criado às 11:30:42.994 UTC, e não apenas o inventário anterior às correções.

| Verificação por caminho original completo + SHA256 | Quantidade |
| --- | ---: |
| Arquivos de output no baseline final P0 | 964 |
| Idênticos encontrados na geração mais recente | 458 |
| Idênticos encontrados na geração anterior | 964 |
| Presentes somente na geração anterior, em relação à mais recente | 506 |
| Encontrados na união, com caminho e SHA256 exatos | **964** |
| Ausentes na união | **0** |
| Encontrados apenas com conteúdo diferente | **0** |

As 964 linhas e os inventários das gerações e do backup de duas partes estão em [P0_OUTPUT_DESLOCADO_PROTECTED_AFTER_UNIAO.json](P0_OUTPUT_DESLOCADO_PROTECTED_AFTER_UNIAO.json). A geração mais recente não contém todos os históricos da anterior; isso não equivale a perda permanente. As gerações não foram misturadas.

A comparação complementar com `PROTECTED_BEFORE.json` identificou 149 arquivos iguais na geração mais recente, três estados correntes modificados e 502 caminhos ausentes dessa geração. Os 502 foram encontrados, todos com o SHA256 anterior, na geração antiga. Os três arquivos correntes são `EDIT_DECISIONS.json`, `series_index.json` e a playlist corrente; a referência correta para a última entrega é o baseline AFTER acima.

## Logs e limite de atribuição

A janela consultada foi 11:30–12:34 UTC, abrangendo os dois eventos de output.

- Security 4663/4688, PowerShell Operational 4103/4104 e Windows PowerShell 400/403/600 retornaram `NoMatchingEventsFound`. Isso não prova que nenhuma operação ocorreu; não há nesses resultados um processo responsável identificável.
- O PSReadLine disponível contém 9.829 linhas. Uma menciona workspace/output e não contém operador destrutivo. O arquivo não registra horário individual de cada comando. Nenhum comando bruto foi copiado para os relatórios.
- O workspaceStorage correspondente do VSCode foi aberto por SQLite com `mode=ro&immutable=1`. Há referências de Explorer, editores e histórico, sem evento de exclusão identificável. Os logs do VSCode de 16/10 inspecionados não forneceram linha candidata.

Detalhes sem tokens, comandos brutos ou valores privados: [eventos Windows](P0_OUTPUT_DESLOCADO_EVENTOS_WINDOWS.json) e [shell/VSCode](P0_OUTPUT_DESLOCADO_SHELL_EDITOR.json). Nenhum log de origem foi alterado. Não houve escrita em USN ou intervenção no Analyzer.

## Registro das ações já realizadas

A chamada de preservação iniciada sob a instrução anterior copiou **1.055 arquivos / 882.836.917 bytes** para `Vídeos/LDPORTO_VIDEO_CURATOR/_quarentena_migracao/recuperacao_20261016_093320`, resolvendo Vídeos pela API do Windows. O journal registra conclusão às **12:45:39 UTC / 09:45:39 em São Paulo**. Quando foi enviada interrupção à sessão, o processo já havia terminado com código zero.

Antes da cópia, todos os arquivos receberam SHA256. Cada cópia foi escrita em arquivo temporário exclusivo, verificada, publicada sem sobrescrever e novamente verificada. Os arquivos e os índices `$I` originais também foram revalidados. A cópia externa inclui um journal adicional; não é uma restauração do aplicativo.

Os registros são [inventário anterior](RECUPERACAO_LIXEIRA_20261016_093320_ANTES.json) e [verificação concluída](RECUPERACAO_LIXEIRA_20261016_093320_VERIFICADA.json). **Nenhum arquivo de produção foi editado, nenhuma árvore foi restaurada em output e nenhum original da Lixeira foi movido ou removido.** Após a ordem de suspensão, não foi iniciada outra cópia, migração ou restauração. Não há processo de cópia pendente.

## Proposta de recuperação — não executada

1. Manter a quarentena, os dois conjuntos da Lixeira e o backup intencional separados e intactos.
2. Após autorização, usar as **1.055 entradas da geração 09:33:20** como candidata ativa, validando novamente caminhos, tamanho e SHA256 contra o inventário anterior à cópia.
3. Conferir que output continua vazio e criar staging inédito, com journal externo. Copiar e verificar, sem sobrescrever destinos concorrentes.
4. Publicar as três árvores nos caminhos originais somente após todas as verificações. Manter os caminhos assinados e os recibos originais; não regenerar aprovações nem refazer curadoria.
5. Validar os oito resultados Reels, as 16 prévias, os vínculos de aprovação e a retomada. Restaurar localização não concede aprovação aos Stories.
6. Em caso de falha, preservar staging e journal. Um rollback deve retirar da área ativa apenas arquivos que ainda tenham exatamente o SHA256 publicado pela recuperação, para outra quarentena; dados divergentes exigem conciliação. Não apagar arquivos para resolver conflito.

O conjunto anterior de 964 arquivos e o backup de duas partes permanecem históricos separados na Lixeira até decisão explícita. Não devem ser sobrepostos à geração ativa proposta. A migração para armazenamento definitivo em Vídeos continua suspensa.
