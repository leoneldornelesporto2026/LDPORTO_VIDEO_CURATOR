# Documentação — L.D.PORTO VIDEO CURATOR

Use este índice como ponto de entrada. Documentação operacional atual fica em `docs/guides/`; decisões técnicas em `docs/architecture/`; arquivos históricos ficam preservados, mas **não representam necessariamente o estado atual do aplicativo**.

## Comece aqui

- [README principal](../README.md)
- [Instalar, abrir e diagnosticar no Windows](guides/WINDOWS.md)
- [Estrutura, responsabilidade de pastas e política de limpeza](architecture/PROJECT_STRUCTURE.md)

## Arquitetura existente

- [Câmera vertical segura](architecture/CAMERA_VERTICAL_SEGURA.md)
- [Legendas alinhadas por palavra](architecture/LEGENDAS_WORD_ALIGNED.md)

## Curadoria e registros

- [Segunda curadoria: arquivos de referência](second_curation/)
- [Histórico de notas, patches e validações](history/README.md)
- [Relatórios técnicos e evidências históricas](reports/)
- [Auditoria anterior de organização e proteção de dados](reports/ORGANIZACAO_PROJETO.md)
- [Validação do fluxo de séries V5](reports/curator_v5/PRIMEIROS_PASSOS_WINDOWS.md)

## Regras

1. `tests/`, `schemas/`, `ldporto_curator/` e scripts de trabalho **não são lixo**.
2. Saídas de renderização, mídias, modelos, credenciais e caches são locais e não devem entrar em commits.
3. Evidências já versionadas precisam de análise de dependências e backup antes de serem retiradas do índice.
4. Documentos de relatório/validação antigos são preservados para auditoria, não executados automaticamente.
