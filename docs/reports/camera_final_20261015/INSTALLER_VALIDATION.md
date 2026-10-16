# Instalador incremental de camera — 15/10/2026

Novo instalador independente: `scripts/INSTALL_CAMERA_FINAL.ps1`. O instalador anterior de legendas foi preservado.

O empacotador `scripts/build_camera_update.py` compara os arquivos com `code_before.json` desta sessao. Alteracoes anteriores ja presentes nesse inventario nao entram no delta. A allowlist aceita somente codigo Python/PowerShell, testes Python e fixtures JSON/JSONL, README, configuracao de pytest e documentacao Markdown explicitamente selecionada. Midia, fontes originais, configuracao local, caches, ambientes, backups e historicos ficam fora do payload. Relatorios antigos nao sao coletados automaticamente.

O ZIP possui SHA256 externo; cada arquivo do payload registra SHA256 anterior, SHA256 novo e tamanho. O instalador faz preflight completo, recusa divergencias locais, caminhos ambiguos, links/junctions e destinos fora da allowlist. `-VerifyOnly` nao escreve arquivos. A atualizacao e idempotente.

Cada instalacao conserva originais e `TRANSACTION.json` em `backups/camera_final_<id>/`. O journal e persistido com flush e substituicao atomica antes/depois de cada alteracao. O arquivo de codigo tambem e substituido atomicamente a partir de copia conferida no mesmo volume. Uma interrupcao entre a substituicao e a atualizacao do journal pode ser recuperada usando `-Rollback`: o instalador reconhece tanto os hashes anteriores quanto os instalados. A recuperacao interrompida pode ser repetida. Uma transacao pendente impede nova instalacao ate sua recuperacao.

Um backup parcial durante a fase PREPARING nao precisa ser usado quando o original ainda confere com o baseline. Backups necessarios a restauracao sao conferidos antes de qualquer alteracao; corrupcao ou edicao local inesperada interrompe o rollback preservando os arquivos existentes. Nao existe exclusao recursiva: o rollback remove apenas arquivos novos da allowlist, com hash instalado confirmado. Backups e journal permanecem disponiveis.

Validacao: `.venv/Scripts/python.exe -m pytest tests/test_camera_update_package.py -q` — **44 passed em 46,66 s** no Windows PowerShell real. Todos os testes de escrita usam diretorios temporarios sinteticos. Foram exercitados verificacao sem escrita, instalacao, repeticao, rollback, hashes incorretos, alteracoes locais, traversal, aliases Windows, destinos protegidos, backups adulterados, junctions e saidas abruptas reais do processo nas etapas de backup, instalacao e rollback. Sentinelas de MP4, projeto, aprovacao, manifest, historico, cache, ambiente, fonte original e backup antigo foram preservadas byte a byte.

O ZIP final deve ser construido somente depois da estabilizacao do codigo e dos relatorios, em pasta separada do baseline, por exemplo `docs/reports/camera_final_package_20261015/update_package`. O pacote nao executa analise, renderizacao, aprovacao editorial ou publicacao. A evidência visual MP4 permanece fora do pacote de codigo.
