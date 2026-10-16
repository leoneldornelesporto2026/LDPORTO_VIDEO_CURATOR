# P0 — diagnóstico do esvaziamento de output

Data: 16/10/2026. Projeto: `LDPORTO_VIDEO_CURATOR`, branch `main`.

## Conclusão comprovada

Os arquivos atuais foram encontrados. Os três subdiretórios de `output` foram enviados à **Lixeira do Windows às 09:33:20, horário de São Paulo**. Os registros preservam seus caminhos originais exatos e os conteúdos continuam presentes. Há também um conjunto anterior, enviado à Lixeira às **08:44:47**.

A geração mais recente contém **1.055 arquivos / 882.836.917 bytes**, incluindo os **8 Reels concluídos** e as **16 prévias de Stories**. Os SHA256 das 24 mídias atuais coincidem com seus registros. A revisão atual dos Reels encontrada é `4489a2650087462ca459d23724415182`, posterior à revisão `6a1b69bda19d4103a932d9223ceb9c81` da entrega P0 anterior. A recuperação deve preservar essa geração mais recente, sem voltar silenciosamente à anterior.

**O mecanismo de desaparecimento foi identificado; o processo ou comando autor da exclusão ainda não foi comprovado.** A presença na Lixeira não permite atribuir a ação ao usuário, ao Curator, ao editor ou a outro programa. Nenhuma dessas atribuições foi feita.

## Evidência física e cronologia

Prefixo da Lixeira que contém os dados:

```text
C:\$Recycle.Bin\S-1-5-21-1047627331-2331748713-3589221872-1001
```

Os arquivos `$I...` guardam caminho original, tamanho e horário de exclusão; os diretórios `$R...` correspondentes contêm os arquivos. Os bytes dos índices e seus SHA256 foram registrados.

| Horário SP | Caminho original | Índice / conteúdo na Lixeira | Bytes declarados |
| --- | --- | --- | ---: |
| 09:33:20.737 | `output\curation` | `$IX0I3Z7` / `$RX0I3Z7` | 121.636.277 |
| 09:33:20.793 | `output\projects` | `$IIEGRZ7` / `$RIEGRZ7` | 448.933.381 |
| 09:33:20.844 | `output\renders` | `$IN5O1OA` / `$RN5O1OA` | 312.267.259 |
| 08:44:47.605 | `output\curation` anterior | `$IBXO5KD` / `$RBXO5KD` | 88.361.659 |
| 08:44:47.643 | `output\projects` anterior | `$IDE1A7L` / `$RDE1A7L` | 360.054.625 |
| 08:44:47.693 | `output\renders` anterior | `$ICK8DW0` / `$RCK8DW0` | 262.007.652 |

O backup mencionado pelo usuário, `_BACKUP_STORIES_2PARTES_20261016_091314`, também foi localizado na Lixeira: `$I6BZZ8B` / `$R6BZZ8B`, às **09:32:24.514**, com 64.096.119 bytes. Isso é um evento separado da movimentação original informada pelo usuário. A investigação não identifica quem o enviou à Lixeira. Ele não foi restaurado nem misturado ao projeto completo de 16 partes.

O diretório `output` existe, está vazio e registra última alteração em **12:33:20.845 UTC / 09:33:20.845 SP**, imediatamente após as três entradas recentes. Sua data de criação é anterior ao incidente. Não foi encontrado um registro de envio da própria raiz `output` à Lixeira; os registros encontrados são dos seus três filhos.

O inventário desta auditoria começou com backup externo às **09:41:20**, depois do evento das 09:33:20, e já encontrou `output` vazio. A conferência final encontrou **12.924 arquivos com SHA256 inalterado**, sem nenhum arquivo ausente em relação àquele inventário. Código, testes, configurações, caches e documentação preexistente permaneceram iguais durante a auditoria.

Evidências: [P0_REGISTROS_LIXEIRA_WORKSPACE.json](P0_REGISTROS_LIXEIRA_WORKSPACE.json), [P0_ESTADO_CAMINHOS.json](P0_ESTADO_CAMINHOS.json), [INVENTARIO_ANTES.json](INVENTARIO_ANTES.json), [P0_VERIFICACAO_FINAL_SOMENTE_LEITURA.json](P0_VERIFICACAO_FINAL_SOMENTE_LEITURA.json).

## O que foi encontrado e validado

| Área recente | Arquivos | Bytes | Verificação |
| --- | ---: | ---: | --- |
| `curation` | 406 | 121.636.277 | Estado, inputs imutáveis, revisões e registros de aprovação preservados. |
| `projects` | 516 | 448.933.381 | Índices, evidência, snapshots, legendas, capas e 16 prévias, incluindo Story 6 separado. |
| `renders` | 133 | 312.267.259 | 8 finais atuais, finais históricos, prévias e recibos. |

Os 8 Reels atuais possuem arquivos presentes na Lixeira e na cópia de proteção, com SHA256 coincidente com os resultados da revisão `4489a2650087462ca459d23724415182`. O estado persistido é `BATCH_COMPLETED`. A leitura do `PlanStore` validou os inputs imutáveis. Os vínculos entre aprovação, prévia, recibos, flag, assinatura e renderizador atual também foram conferidos sem reescrever arquivos.

As 16 prévias dos Stories mantêm **S01: 3, S02: 5, S03: 8**. Quinze estão referenciadas no projeto `stories_30af3ad6a05923e2`; o Story 6 está em `story06_caption_recovered_047cafe2e748`. As assinaturas dos 16 episódios foram reproduzidas exatamente e os assets referenciados conferem com o inventário. **Nenhum Story foi convertido em aprovado.**

Exemplos verificáveis:

- Reel 1 atual, `SECOND_LDP26_REEL_01_01_FINAL.mp4`: SHA256 `82fa058d5d5ffc0251ac5f4ae6899050f7623fcd4305fc68281a6fa44f6a0b87`.
- Story 6 atual, `...\story06_caption_recovered_047cafe2e748\...\c20a8019f04c748e\preview\PREVIEW_540x960.mp4`: SHA256 `a71843925517db816d75324edb763a5cba384aaadbdd4b23b34567e158bccb07`. Sua assinatura de plano é `c20a8019f04c748ef9344edf808eff568ea7ab367386e597b205b37b40f64944`.
- Original do Analyzer: `..\LDPORTO_VIDEO_ANALYZER\input\youtube\zd_wjssZ7mc\zd_wjssZ7mc.mp4`, ainda no local original, SHA256 `b2958122415980a8afff4f77c23ead3c31c00345e5df0ab460995eb731efb00f`.

O conjunto das 08:44:47 e a documentação anterior foram mantidos separados da geração das 09:33:20. A comparação adicional com `PROTECTED_AFTER.json` da entrega P0 anterior encontrou **964/964 arquivos de output com o mesmo caminho original e SHA256 exato no conjunto das 08:44:47**. A geração recente mantém 458 desses arquivos; os outros 506 históricos estão na geração anterior. Na união das gerações: **964 correspondências, zero ausentes e zero divergentes** em relação àquele baseline. Não foi feito merge de estados antigos e novos.

Essa confirmação cobre o inventário daquela entrega e os arquivos atuais indexados; não afirma conhecer todos os arquivos que já existiram no computador. Comparação completa: [P0_OUTPUT_DESLOCADO_PROTECTED_AFTER_UNIAO.json](P0_OUTPUT_DESLOCADO_PROTECTED_AFTER_UNIAO.json).

Lista completa dos 24 arquivos atuais, caminhos reais, SHA256, verificações de assets/aprovações e comparação histórica: [P0_OUTPUT_DESLOCADO_DIAGNOSTICO.json](P0_OUTPUT_DESLOCADO_DIAGNOSTICO.json).

## Rotinas auditadas e relação com o incidente

Foi feita leitura estática de entradas, módulos de produção, scripts e testes; os testes não foram executados nesta investigação. O catálogo [OPERACOES_ARQUIVOS.json](OPERACOES_ARQUIVOS.json) registra as chamadas potencialmente relacionadas a arquivos para inspeção contextual.

| Caminho | Comportamento encontrado | Relação comprovada com os três diretórios na Lixeira |
| --- | --- | --- |
| `app.py`, `ABRIR_CURADOR.bat`, `gui.App.__init__` | Carregam dependências, GUI e sessão; não chamam limpeza. | Nenhuma. |
| `gui.open_results`, linhas 539–546 | Pode criar a pasta de saída se ela estiver ausente. | Pode explicar uma pasta recriada vazia em outro cenário; não explica a exclusão dos filhos nem comprova que o botão foi usado. |
| `Pipeline.read_state` / persistência | Pode conciliar estado legado/interrompido e gerenciar locks; não remove árvores de mídia. | Nenhuma. |
| `gui.clean_heavy` / `storage_dialog` | Limpeza exige abertura explícita do diálogo e confirmação da lista. | Não há registro disponível de acionamento no horário do incidente. |
| `storage.execute_cleanup`, linhas 220–244 | Remove apenas scratch PNG/WAV/TMP registrado, com SHA256 e caminho revalidados; bloqueia `output`, projetos, renders, caches, backups e fontes. Usa `unlink` de arquivo, não exclusão recursiva ou Lixeira. | O código atual não explica três árvores inteiras com MP4 e JSON na Lixeira. |
| Render de Reels/Stories | Usa revisão/tentativa própria, publicação exclusiva e remoção apenas do parcial próprio já publicado. | Nenhuma chamada encontrada que envie `curation`, `projects` e `renders` à Lixeira. |
| Instaladores PowerShell | `Remove-Item` restrito a arquivos novos do pacote durante rollback, com allowlist e hashes; sem `-Recurse` e sem `output` na allowlist. | Nenhuma. |
| Testes de proteção e render | Escritas/remoções ficam em `tmp_path`; testes legados copiam originais para temporários antes de escrever. | Não foram executados nesta fase; não há evidência de que tenham produzido o incidente. |
| Importação / `SeriesProject.save` | Escrevem metadados e snapshots; não há remoção recursiva das três árvores. | Não explicam os registros de Lixeira. |

A busca no código ativo não encontrou `send2trash`, `SHFileOperation`, `IFileOperation`, API de Lixeira ou `rmtree`. Essa conclusão é delimitada ao código atual auditado e não certifica programas externos, versões históricas executadas ou comandos sem registro.

Foi encontrado um risco separado de persistência: `utils.load_json` captura exceções e pode devolver `{}` para um índice corrompido; `SeriesProject.create_stories` pode então tratar o projeto como inexistente e salvar metadados. Esse risco merece correção após a investigação, mas **não explica o envio das três árvores à Lixeira**. Nenhuma correção foi aplicada nesta fase.

Detalhes da inicialização e limpeza: [DIAGNOSTICO_GUI_EXCLUSAO_OUTPUT_P0.md](DIAGNOSTICO_GUI_EXCLUSAO_OUTPUT_P0.md) e [GUI_STARTUP_PROTECTED_OPERATIONS_P0.json](GUI_STARTUP_PROTECTED_OPERATIONS_P0.json).

## Logs e limites da atribuição

As consultas aos eventos Security 4663/4688, PowerShell 4103/4104 e Windows PowerShell 400/403/600 não retornaram eventos correspondentes na janela examinada. O histórico PSReadLine não forneceu comando destrutivo relacionado ao workspace; suas linhas não possuem timestamps individuais. Os registros do VS Code examinados mostraram referências ao workspace, sem evento de exclusão identificável. Valores e comandos privados não relacionados não foram copiados para os relatórios.

Isso deixa **sem comprovação o executável, PID, comando e autor que enviaram os diretórios à Lixeira**. Não é correto concluir que o Curator os apagou, nem excluir essa possibilidade histórica apenas pela leitura do código atual.

Registros da investigação: [P0_OUTPUT_DESLOCADO_EVENTOS_WINDOWS.json](P0_OUTPUT_DESLOCADO_EVENTOS_WINDOWS.json), [P0_OUTPUT_DESLOCADO_SHELL_EDITOR.json](P0_OUTPUT_DESLOCADO_SHELL_EDITOR.json).

## Cópia de proteção e suspensão das operações

Antes de chegar a nova instrução do usuário para suspender cópias/migrações, uma cópia de proteção da geração recente já havia sido concluída e verificada em:

```text
C:\Users\leone\Videos\LDPORTO_VIDEO_CURATOR\_quarentena_migracao\recuperacao_20261016_093320
```

São os 1.055 arquivos, com tamanho e SHA256 conferidos, preservando as três árvores. Os conteúdos originais da Lixeira e seus índices foram novamente conferidos e permaneceram idênticos. A cópia não alterou os caminhos ativos, os manifests ou as aprovações. **Nada foi restaurado em `output`.**

Depois da suspensão, não houve nova cópia, migração, limpeza, alteração de produção, execução de testes, renderização ou rollback. Foram feitas leituras e gravados relatórios de diagnóstico. A conferência completa do baseline atual não encontrou nenhuma alteração nos 12.924 arquivos existentes com hash.

Comprovação da cópia: [RECUPERACAO_LIXEIRA_20261016_093320_ANTES.json](RECUPERACAO_LIXEIRA_20261016_093320_ANTES.json) e [RECUPERACAO_LIXEIRA_20261016_093320_VERIFICADA.json](RECUPERACAO_LIXEIRA_20261016_093320_VERIFICADA.json).

## Recuperação proposta

A proposta é restaurar **cópias byte a byte da geração das 09:33:20 nos caminhos originais**, preservando Lixeira e quarentena como fontes de rollback. Isso recupera os vínculos existentes sem editar hashes, manifests, revisões, nomes ou aprovações, e sem renderizar novamente os 8 Reels ou os 16 Stories.

O plano foi preparado somente como diagnóstico/dry-run: **1.055 destinos ausentes**, aproximadamente **883 MB**, com espaço disponível suficiente. Ele contém origem, destino original e SHA256 de cada arquivo. A implementação e a execução da restauração não foram iniciadas.

Procedimento, gates e rollback: [PROPOSTA_RECUPERACAO_OUTPUT_P0.md](PROPOSTA_RECUPERACAO_OUTPUT_P0.md). Mapa completo: [P0_PLANO_RESTAURACAO_DRY_RUN.json](P0_PLANO_RESTAURACAO_DRY_RUN.json).

A auditoria global e a migração definitiva de mídias permanecem suspensas, conforme a prioridade P0 informada pelo usuário.
