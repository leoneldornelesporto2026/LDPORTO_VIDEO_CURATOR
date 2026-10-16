# P0 — inicialização, botão de limpeza e ausência de output

Diagnóstico estático complementar, 16/10/2026. A tarefa de alterações globais foi suspensa. Nenhum arquivo de produção/configuração/teste foi alterado por este agente; nenhuma GUI, teste, limpeza, migração, restauração ou rollback foi executado. Os únicos arquivos criados por este agente são relatórios em `docs/reports/auditoria_global`.

## Conclusão delimitada

`output` existe e foi encontrado com **zero entradas**, antes de qualquer alteração de produção por este agente. Os hashes de 15 arquivos usados na investigação e o stat do diretório estão em [GUI_STARTUP_PROTECTED_OPERATIONS_P0.json](GUI_STARTUP_PROTECTED_OPERATIONS_P0.json).

Não foi identificado no código ativo examinado um caminho que exclua recursivamente `output` ou envie seu conteúdo à Lixeira. A entrada na Lixeira relatada pela investigação principal precisa ser correlacionada com histórico/comandos e horários; esta leitura estática não identifica quem executou a operação. Não foram examinados nem modificados os bytes da Lixeira por este agente.

## O que a abertura faz

`ABRIR_CURADOR.bat:3–23` muda para a raiz, verifica ambiente/dependências, eventualmente instala requisitos se faltarem, e executa `app.py`. O BAT não contém comando de limpeza. `app.py:1–3` chama `gui.launch`.

`gui.App.__init__:31–57` carrega YAML, constrói widgets, restaura sessão e agenda consumo de fila. Não chama `clean_heavy`, `show_cleanup` ou `execute_cleanup`.

`gui._restore_session:369–383` lê `.cache/gui_session_v52.json`. Se a sessão for válida, chama `_refresh_plan_state`, que captura valores e inicia worker (`gui.py:396–452`). O worker usa `Pipeline.read_state`.

`Pipeline.read_state:178–182` localiza um projeto já persistido e adquire lock. O método não é estritamente somente leitura em todos os estados: `_load:86–114` pode derivar uma revisão legada ou conciliar um lote interrompido. `pipeline_recovery.py:61–73` cria revisão e estado sem remover original; `pipeline._recover_batch_state` preserva histórico de resultados. Os locks removidos em `persisted_plan.py:288–327` são exclusivamente arquivos `.PLAN_OPERATION.lock`/`.reclaim`, com checagem de token/PID. Essas operações não excluem árvore de mídia.

Quando não há `EDIT_DECISIONS.json`, `_project_dir:68–84` apenas procura e lança `FileNotFoundError`; não recria o lote. O botão **Abrir resultados**, ao contrário, faz `mkdir(parents=True,exist_ok=True)` do destino (`gui.py:539–546`). Esse botão pode criar uma pasta de saída vazia que estava ausente, sem provar a causa de uma perda anterior.

## O que o botão de limpeza permite hoje

O botão é ligado apenas ao callback explícito `clean_heavy` (`gui.py:109`). O callback (`gui.py:586–595`) retorna se há operação ativa e solicita uma pasta via `askdirectory`. Cancelar a escolha encerra o caminho.

`storage_dialog.show_cleanup:22–49` primeiro executa `cleanup_preview`, que apenas lê diretórios, metadados e hashes. O botão de remoção é desabilitado quando a lista elegível é vazia. A única chamada a `execute_cleanup(...,confirmed=True)` ocorre após `messagebox.askyesno` retornar verdadeiro (`storage_dialog.py:38–43`).

As restrições de `storage.py` são cumulativas:

1. `output`, `.cache`, `source_cache`, `.venv`, `projects`, `revisions`, `renders`, `backups`, `analysis`, `docs` e outros nomes protegidos bloqueiam todos os descendentes (`15–21`, `136–159`). A checagem considera os ancestrais reais, não apenas o nome da pasta escolhida.
2. Só extensões `.png`, `.wav` e `.tmp`, sob `temporary_frames` ou `render_staging`, podem ser elegíveis (`28`, `119–129`, `145–147`). MP4 e JSON não são elegíveis.
3. Exige manifesto `.ldporto_temporary_files.json` com schema, caminho relativo válido, propósito `regenerable_scratch`, tamanho e SHA256 exatos (`104–133`, `162–171`). Arquivos antigos não são cadastrados automaticamente.
4. Fonte selecionada, links/junctions, marcadores de projeto/Analyzer, locks e arquivo em uso são preservados (`84–96`, `148–156`, `166–167`).
5. Antes da remoção, valida novamente política, manifesto, tamanho, mtime, caminho, elegibilidade e SHA256 (`220–244`).

A operação final é `path.unlink()` de cada scratch autorizado (`storage.py:240`), sem remoção de diretório e sem chamada de API de Lixeira. Nenhuma rotina de inicialização registra automaticamente arquivos de `output` como scratch. O caminho atual não explica o desaparecimento de todos os MP4 e metadados da raiz de saída.

Essa conclusão não certifica versões históricas diferentes. Backups e comandos antigos precisam ser comparados separadamente, e os testes existentes ainda não foram executados nesta fase P0.

## Demais operações de remoção encontradas

| Local atual | Objeto removido / proteção observada |
| --- | --- |
| `storage.py:73–81` | Arquivo de lease UUID `.ldporto_media_use_*.json` criado pela própria chamada; não a mídia. |
| `persisted_plan.py:236–248` | Temporário UUID de gravação atômica. |
| `persisted_plan.py:288–327` | Locks próprios ou locks com PID comprovadamente morto/token inalterado. |
| `render.py:473–491` | Nome `ENCODING_<uuid>_...mp4` após validação e publicação por hardlink exclusivo. O MP4 definitivo permanece. |
| `series_workflow.py:749–903`, em especial `863` | Parcial próprio após publicação; tentativas/revisões anteriores têm destinos próprios. |
| `combined_batch.py:376–405` | Temporário criado por `mkstemp` na mesma invocação, depois da publicação por hardlink. |
| `INSTALL_CAMERA_FINAL.ps1:115–128` | Rollback remove um arquivo novo do pacote somente quando não havia original; allowlist exclui output/cache/revisões e verifica hashes. Não é chamado no startup. |
| `INSTALL_CAPTIONS_P0.ps1:72–80,141–149` | Rollback de arquivos novos do pacote em caminhos permitidos. Não é chamado no startup. |

A busca textual em módulos de produção, scripts, testes e entradas da raiz não encontrou `send2trash`, `SHFileOperation`, `IFileOperation`, `RecycleBin` ou `rmtree` no código ativo. Foram excluídos `.venv`, `.git`, caches e snapshots históricos de `docs/reports` dessa conclusão. `str.replace` e substituições de texto foram diferenciadas de operações de arquivo.

## Evidência que falta para atribuir a causa

- Registro original da Lixeira: caminho anterior, horário de exclusão, quantidade/tamanho e hashes do conteúdo recuperável, sem restauração nesta fase.
- Correlação com histórico de comandos/ações, logs e diferenças de versões no horário do incidente. A presença de um arquivo na Lixeira, sozinha, não identifica o processo autor.
- Comparação dos inventários anteriores com a árvore recuperável mais recente, separando metadados/revisões aprovadas de snapshots de demonstração.
- Plano explícito de recuperação com destino e colisões resolvidos, antes de copiar/restaurar qualquer arquivo.

Nada foi restaurado, movimentado, apagado ou revertido por este agente. As propostas de desempenho/GUI do relatório amplo permanecem pendentes e não foram iniciadas.
