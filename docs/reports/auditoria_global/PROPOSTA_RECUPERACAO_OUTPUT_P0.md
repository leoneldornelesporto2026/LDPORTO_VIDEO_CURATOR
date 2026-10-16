# Recuperação proposta — sem execução

O usuário solicitou primeiro diagnóstico e proposta. **Este procedimento ainda não foi executado.** `output` continua vazio. Não há necessidade de inventar ou reconstruir aprovações: os arquivos recentes foram encontrados íntegros.

## Geração correta e mapa

Usar somente a geração enviada à Lixeira em **16/10/2026 às 09:33:20 SP**, já copiada e verificada na quarentena. Ela contém a revisão de Reels `4489a2650087462ca459d23724415182`, o projeto de Stories de 16 episódios e a recuperação `story06_caption_recovered_047cafe2e748`.

Prefixo de origem verificado:

```text
C:\Users\leone\Videos\LDPORTO_VIDEO_CURATOR\_quarentena_migracao\recuperacao_20261016_093320
```

Prefixo de destino original:

```text
C:\Users\leone\Documentos\Meus Projetos\LDPORTO_VIDEO_CURATOR\output
```

| Origem na quarentena | Destino proposto | Arquivos |
| --- | --- | ---: |
| `curation\...` | `output\curation\...` | 406 |
| `projects\...` | `output\projects\...` | 516 |
| `renders\...` | `output\renders\...` | 133 |

Total: **1.055 arquivos / 882.836.917 bytes**. Cada caminho, tamanho e SHA256 está em [P0_PLANO_RESTAURACAO_DRY_RUN.json](P0_PLANO_RESTAURACAO_DRY_RUN.json). No dry-run, todos os destinos estavam ausentes; havia aproximadamente 163 GB livres no volume.

O conjunto das 08:44:47 deve continuar separado como histórico: ele contém os **964 arquivos e SHA256 exatos do output da entrega P0 anterior**, incluindo 506 históricos que não constam da geração recente. Na execução posteriormente autorizada, preservar também uma cópia externa independente dessa geração e verificar seus hashes, antes de qualquer conciliação. O backup incompatível de dois Stories não deve ser ativado ou misturado à sequência de 16 partes. Arquivos históricos só devem ser conciliados depois, por caminho e SHA256, preservando versões divergentes. Essa cópia histórica adicional ainda não foi realizada.

## Pré-condições antes de executar

1. Fechar o Curator, que foi encontrado aberto durante a investigação, para evitar gravações concorrentes. Não interromper o Analyzer de outro vídeo.
2. Revalidar todos os SHA256 da fonte da Lixeira, da cópia de proteção e dos índices `$I` contra os inventários preservados.
3. Conferir que `output` ainda está no mesmo caminho e sem novos dados. Qualquer arquivo surgido depois do diagnóstico exige conciliação: nunca sobrescrever uma divergência.
4. Verificar espaço livre, destinos absolutos confinados a `output` e ausência de redirecionamentos/junctions inesperados.
5. Criar journal externo inédito com o mapa completo e os estados de cada arquivo/árvore. Os backups novos continuam fora do repositório.

## Restauração transacional proposta

1. Copiar a geração recente para staging de nome exclusivo, sem escrever diretamente nos destinos definitivos e sem remover as fontes.
2. Conferir tamanho e SHA256 de todos os 1.055 arquivos. Interrupção deixa staging e journal preservados; a retomada reutiliza somente cópias já conferidas.
3. Promover cada árvore verificada para seu nome original, com publicação exclusiva e recusa de colisões. Registrar no journal cada promoção; não abrir a GUI enquanto as três árvores não estiverem completas.
4. Revalidar todos os arquivos no destino, por tamanho e SHA256. Nenhum JSON deve ser reserializado ou ter caminhos/hashes editados: os caminhos originais voltam a existir.
5. Verificar o `PlanStore`, a revisão ativa dos Reels e os vínculos de aprovação; conferir os 24 MP4s e todos os assets referenciados.
6. Abrir o Curator e confirmar retomada e reprodução das mídias existentes, sem executar CURAR, Qwen, transcrição ou lote de renderização. A aprovação audiovisual dos Stories permanece pendente.
7. Encerrar com manifesto de restauração, comparação antes/depois e lista de eventuais pendências. Manter fontes e cópias de segurança.

A promoção das três árvores não é uma operação única do sistema de arquivos; o journal precisa permitir retomar com segurança uma interrupção entre elas. A GUI deve permanecer fechada até a validação completa.

## Rollback sem exclusão

Os originais da Lixeira e a cópia de proteção permanecem disponíveis durante todo o procedimento. Se uma restauração parcial precisar ser revertida, conferir os arquivos promovidos contra o journal e preservar essas árvores em um novo diretório externo de rollback. Não apagar arquivos nem substituir versões históricas.

Se houver edição humana posterior à restauração, interromper rollback automático e conciliar as diferenças antes de qualquer movimentação. Não usar `git reset`, `git clean`, remoção recursiva, comandos de espelhamento com purge ou esvaziamento da Lixeira.

## Critérios de aceite

- Os 1.055 arquivos restaurados coincidem com seus SHA256 preservados.
- A revisão ativa é a recente `4489a2650087462ca459d23724415182`, com 8 Reels existentes.
- Os Stories mantêm 16 episódios, ordem 3/5/8 e o Story 6 recuperado.
- MP4s, legendas, títulos, câmera, revisões e aprovações permanecem iguais aos encontrados.
- Nenhuma nova aprovação, curadoria, análise ou renderização foi criada.
- Uma nova abertura encontra as mesmas mídias e não elimina arquivos.

Após essa recuperação ser concluída e validada, retomar a auditoria global e preparar separadamente a migração definitiva para a pasta Vídeos.
