# L.D.PORTO VIDEO CURATOR

**Curadoria, revisão e renderização vertical** a partir das análises do [L.D.PORTO VIDEO ANALYZER](https://github.com/leoneldornelesporto2026/LDPORTO_VIDEO_ANALYZER).

O Curator transforma uma análise concluída em propostas de cortes, planos de câmera, legendas, capas, prévias e renders para revisão humana. A decisão de publicar ou renderizar em lote **não é automática**.

> **Escopo deste repositório:** este README documenta o código disponível na branch atual. Os relatórios históricos descrevem entregas específicas; não são prova de que dependências locais, modelos, mídias ou testes estejam disponíveis na sua máquina.

## Início rápido — Windows

1. Instale **Python 3.11** e **FFmpeg/FFprobe** (no PATH).
2. Execute `INSTALAR.bat` para criar `.venv` e instalar `requirements.txt`.
3. Ajuste `paths.analysis_root` em `config.yaml` para o diretório de análises do Analyzer.
4. Execute **`ABRIR_CURADOR.bat`** para abrir a interface.
5. Informe a URL de um vídeo **já analisado**, clique em **CURAR** e depois em **TESTAR 1 CORTE**.
6. Assista à prévia, **APROVAR TESTE** e só então **RENDERIZAR TODOS**.

O bloqueio de renderização em lote é configurado em `safety.require_first_test_approval_before_batch`. O projeto pode precisar de outras ferramentas locais (por exemplo, Ollama), conforme a operação e a configuração escolhida.

**Guia completo:** [Instalação e comandos Windows](docs/guides/WINDOWS.md).

## Comandos de referência

```powershell
# Abrir GUI
.\ABRIR_CURADOR.bat

# Diagnóstico
.\scripts\windows\DIAGNOSTICO.bat

# Teste de um corte, após instalação e com análise disponível
.\scripts\windows\TESTAR_1_CORTE.bat "https://www.youtube.com/watch?v=ID_DO_VIDEO" 1

# CLI — ver opções sem processar mídia
.\.venv\Scripts\python.exe cli.py --help

# Testes automatizados (pytest precisa estar instalado)
.\.venv\Scripts\python.exe -m pytest -q tests
```

`cli.py` também possui fluxos para segunda curadoria, planejamento de séries, dossiês e aprovação de episódios. Leia [Operação e limites](docs/guides/WINDOWS.md) antes de executar alterações ou renders.

## Organização do repositório

| Caminho | Finalidade |
| --- | --- |
| `app.py`, `cli.py` | Entrada GUI e CLI |
| `ldporto_curator/` | Código da aplicação, pipeline, câmera, legendas e revisão |
| `config.yaml`, `curation_overrides.json` | Configuração e decisões opcionais de curadoria |
| `tests/`, `schemas/`, `examples/` | Testes, contratos e exemplos |
| `scripts/` | Ferramentas auxiliares, instaladores e verificações |
| `docs/` | Guias, arquitetura, documentação histórica e evidências |
| `output/`, `source_cache/`, `.venv/` | Dados locais e ambientes; não devem ser publicados no Git |

**Somente dois lançadores essenciais permanecem na raiz:** `INSTALAR.bat` e `ABRIR_CURADOR.bat`. Os comandos auxiliares ficam em `scripts/windows/`.

## Documentação

- [Índice de documentação](docs/README.md)
- [Estrutura e critérios de preservação](docs/architecture/PROJECT_STRUCTURE.md)
- [Câmera vertical segura](docs/architecture/CAMERA_VERTICAL_SEGURA.md)
- [Legendas alinhadas por palavra](docs/architecture/LEGENDAS_WORD_ALIGNED.md)
- [Segunda curadoria](docs/second_curation/)
- [Arquivo de notas e entregas históricas](docs/history/README.md)

## Segurança e integridade

- Não inclua tokens, credenciais, vídeos, modelos, caches ou `.venv` no repositório.
- **Não apague `output/`, `source_cache/`, revisões ou evidências locais** sem backup e validação dos vínculos.
- Algumas evidências e duplicações históricas em `docs/reports/` já estão rastreadas. O `.gitignore` evita novos arquivos correspondentes, **mas não retira automaticamente arquivos existentes do histórico**.
- Mantenha testes, fixtures, schemas e os caminhos usados pelo aplicativo.
- Desenvolvimento em `develop`; `release` e `main` não são promovidas automaticamente.

Os atalhos e a documentação foram organizados sem alteração no código do motor de curadoria.
