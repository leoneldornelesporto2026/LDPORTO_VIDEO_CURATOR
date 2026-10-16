# Proteção de saídas, originais e histórico — 15/10/2026

A causa do esvaziamento anterior de `output` não foi determinada. A revisão do código atual identifica riscos concretos e acrescenta barreiras preventivas; não permite atribuir o incidente a uma rotina, pessoa ou execução anterior.

O baseline desta sessão está em `protected_before.json`, `code_before.json` e `backup_before/`, neste diretório. Nenhuma limpeza foi executada. Não foram apagados `output`, `.cache`, `source_cache`, `.venv`, arquivos originais ou backups.

## Auditoria do código ativo

| Rotina | Comportamento constatado antes deste refinamento | Tratamento |
| --- | --- | --- |
| `storage.cleanup_preview` / `execute_cleanup` | Podiam listar e excluir a fonte original explicitamente selecionada, inclusive externa à pasta do preview. Classificavam WAV de `audio/`, imagens/áudio de staging e arrays de `.cache` como regeneráveis por nome e extensão. | Fonte sempre preservada; árvores protegidas bloqueadas; origem regenerável precisa de registro exato e SHA256. |
| `storage_dialog.show_cleanup` / `gui.clean_heavy` | Interface permitia escolher uma pasta arbitrária e incluir o original na limpeza. | A opção de apagar o original foi retirada. A interface informa a política e os possíveis temporários que foram preservados. |
| `render._base_cmd` / `_render_clip` | FFmpeg utilizava `-y` no destino e o renderizador produzia nomes previsíveis. Esse uso podia sobrescrever um destino existente quando invocado diretamente sem isolamento. | A rotina agora gera pending UUID com `-n`, valida antes de publicar e usa hard link exclusivo para recusar colisão. Um recibo permanente de tentativa impede writers concorrentes antes da geração de assets. Demonstrações usam diretórios inéditos em `docs/reports/`. |
| `series_workflow.SeriesProject.save` | Preserva o índice anterior em revisão por hash e substitui atomicamente o índice corrente. Arquivos derivados são atualizados durante save. | Não é uma limpeza; projetos históricos reais não devem ser salvos por testes ou demonstrações. |
| `persisted_plan._atomic_json` / `_exclusive_lock` | `unlink` é aplicado a temporários próprios e locks, com verificação do proprietário/token nos locks. | Não foi identificada exclusão recursiva do conteúdo de output nessas funções. |
| `scripts/INSTALL_CAPTIONS_P0.ps1` | Possui remoções pontuais de arquivos novos de código no rollback; escopo e SHA256 são verificados. Não há `Remove-Item -Recurse`. | Instalador histórico preservado. O pacote de câmera terá instalador específico. |
| Scripts de validação, recuperação e demonstração | Escrevem relatórios, cópias ou revisões; alguns usam nomes fixos de relatório. Não são inicialização do aplicativo. | Não executar indiscriminadamente nem reaproveitar diretório de demonstração existente. |
| Inicialização/importação | `app.py` inicia GUI; a configuração resolve caminhos. Não foi encontrada limpeza automática de `output` na inicialização. | A ausência no código atual não prova a origem do incidente anterior. |

A busca no código Python/PowerShell/BAT ativo não encontrou chamada de exclusão recursiva (`rmtree`, `Remove-Item -Recurse`, `rd /s`) usada para limpar dados do usuário. Cópias arquivadas de código e pacotes anteriores em `docs/reports/` são histórico, não módulos duplicados a excluir.

## Política preventiva aplicada

`storage.py` mantém a API de preview e confirmação, mas passa a preservar todo arquivo antigo ou incerto. A pasta ou extensão, sozinha, não é prova de que um arquivo pode ser reconstruído.

- `output`, `.cache`, `source_cache`, `.venv`, originais, backups, projetos, revisões, aprovações, evidências e relatórios são bloqueados para limpeza.
- A fonte fornecida à API é preservada mesmo que um chamador antigo ainda passe `include_source=True`.
- Arquivos persistidos como MP4, JSON, manifests, flags, legendas e pacotes nunca são elegíveis. A política não depende de o MP4 se chamar FINAL.
- Diretórios com marcadores de projeto ou evidência do Analyzer são protegidos, mesmo fora dos nomes usuais.
- Symlinks e junctions são verificados antes da resolução de caminhos. O preview não percorre destinos redirecionados. A execução revalida caminhos, locks, lease de mídia e hashes.
- Somente PNG/WAV/TMP gerados dentro de `temporary_frames/` ou `render_staging/`, fora de árvores protegidas, podem ser considerados quando há registro correspondente em `.ldporto_temporary_files.json` (`LDP_GENERATED_SCRATCH_V1`, finalidade `regenerable_scratch`, caminho relativo, bytes e SHA256).
- Nenhum arquivo existente é registrado automaticamente. Nenhum produtor atual foi alterado para registrar dados antigos; portanto possíveis temporários preexistentes continuam preservados. Essa política conservadora pode reduzir o espaço liberável a zero.
- Preview antigo é recusado. Manifest alterado/corrompido, arquivo alterado até com mesmo tamanho/mtime, lock novo ou novo marcador de projeto fazem a execução preservar o arquivo.
- Lease de mídia interrompido ou de proprietário desconhecido preserva os arquivos da pasta; uma falha de leitura não é autorização para limpeza.
- A lista `preserved_candidates` contém caminho, bytes e motivo dos possíveis temporários preservados para uma auditoria futura. Não autoriza limpeza.

O registro é uma declaração explícita do produtor de temporários, não uma comprovação editorial. O teste sintético desse mecanismo não registra nem limpa arquivos reais.

## Testes e isolamento

`tests/test_output_protection.py` escreve apenas em `tmp_path`. O teste cria MP4s/JSONs/flags de bytes sintéticos, cópias de manifests e junctions dentro de diretórios descartáveis. Nenhuma rotina de teste chama limpeza no projeto real.

Os casos cobrem: preview somente leitura; preservação de todo output e caches; originais internos e externos; histórico e evidências; necessidade de confirmação; registro válido de scratch sintético; plano forjado; preview antigo; alteração de conteúdo sem mudar tamanho/mtime; manifest interrompido; lock inserido depois do preview; falha de render com lease; junction no root e substituição de staging por junction após o preview.

`tests/test_render_output_protection.py` exercita falhas e publicação concorrente com encoder controlado, sem tocar mídia real. Cobre: recusa de reuso após sucesso ou interrupção; recuperação em uma pasta nova; falha de validação antes da publicação; outro writer publicando primeiro; falha do sidecar depois da publicação; fallback NVENC com nomes diferentes; claim antes de gerar assets; preservação de resíduos como legendas, títulos, manifests e relatórios de verificação. O arquivo parcial e o recibo de tentativa são mantidos após falha, e jamais são tratados como aprovação.

A auditoria dos testes existentes não encontrou escrita em output/cache reais: os testes de recuperação legada leem o histórico original, verificam hashes e copiam para `tmp_path` antes de modificar. `audit_real_cached_preview` executa leitura e ffprobe. Os demais fluxos de escrita encontrados usam fixtures ou diretórios temporários. Configuração real lida em `test_core` é usada com dados de fixture; não dispara exportação.

Execução recomendada: Python com `PYTHONDONTWRITEBYTECODE=1`, pytest com `-p no:cacheprovider` e `--basetemp` inédito dentro do diretório temporário do sistema. Não usar `output` ou cache do usuário como base de testes. Os resultados automatizados e a comparação SHA256 final são registrados pelo relatório geral desta sessão.

## Limites e itens preservados

Não há promessa de bloquear ações externas feitas por Explorer, terminal ou outro programa. As barreiras são aplicadas às rotinas auditadas do Curator; a verificação independente dos hashes confirma a preservação dos arquivos reais desta sessão.

Não foram removidos módulos, dependências, scripts antigos, backups, pacotes ou relatórios. Arquivos de origem incerta continuam disponíveis. Teste bem-sucedido ou render de demonstração não concede aprovação humana ou editorial.
