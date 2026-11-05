# Estrutura do projeto e regras para organização

A estrutura deste repositório separa código executável, contratos, documentação e material de trabalho. Uma organização de pastas não deve alterar o comportamento do pipeline ou invalidar aprovações.

```text
LDPORTO_VIDEO_CURATOR/
├── ABRIR_CURADOR.bat
├── INSTALAR.bat
├── app.py
├── cli.py
├── config.yaml
├── curation_overrides.json
├── requirements.txt
├── pytest.ini
├── ldporto_curator/           # lógica principal do sistema
├── scripts/
│   └── windows/              # comandos auxiliares movidos da raiz
├── tests/                    # testes ativos e fixtures
├── schemas/                  # contratos dos dados
├── examples/                 # exemplos versionados
├── docs/
│   ├── guides/
│   ├── architecture/
│   ├── history/
│   ├── second_curation/
│   └── reports/              # auditorias e evidências históricas
├── .venv/                     # local: ignorado pelo Git
├── output/                    # local: renders e revisões
└── source_cache/              # local: mídias e estados de trabalho
```

As três últimas pastas são ilustrativas: podem não existir em uma clonagem limpa.

## O que manter

- Código: `ldporto_curator/`, `app.py`, `cli.py`.
- Configuração e interfaces: `config.yaml`, `curation_overrides.json`, arquivos BAT principais.
- Testes/fixtures: `tests/`, `schemas/`, `examples/`.
- Ferramentas: `scripts/`.
- Documentação de referência: `docs/architecture/`, `docs/guides/`, `docs/second_curation/`.

## O que não versionar daqui para frente

- `.venv/`, `__pycache__/`, caches de IA, modelos e pesos baixados.
- Vídeos, faixas de áudio, renders, prévias, arquivos temporários.
- Credenciais e variáveis locais de ambiente.
- Novos backups e snapshots de `output/` ou `source_cache/`.
- Grandes evidências automaticamente geradas (conforme regras específicas no `.gitignore`).

`docs/reports/` possui snapshots e evidências repetidas, inclusive arquivos grandes. A limpeza **não apaga** esses arquivos agora, pois um teste, auditoria ou projeto histórico pode depender de seus caminhos ou hashes. O próximo passo, se autorizado, é separar e arquivar evidências com manifesto de integridade e verificar a regressão antes de retirar arquivos rastreados.

**Importante:** `.gitignore` não remove arquivos já rastreados nem limpa o histórico Git. Remover arquivos da versão atual, excluir dados físicos e reescrever o histórico são operações distintas.
