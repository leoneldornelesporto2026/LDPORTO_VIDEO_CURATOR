# Instalação e operação — Windows

## Requisitos

- Windows com `py -3.11` disponível.
- FFmpeg e FFprobe no PATH para renderização/verificação.
- Dependências Python do `requirements.txt` instaladas em `.venv`.
- Para fluxos configurados para IA local, Ollama e o modelo indicado em `config.yaml` devem estar acessíveis. A disponibilidade do serviço/modelo depende da máquina.
- Análise prévia concluída no L.D.PORTO VIDEO ANALYZER ou pacote compatível.

## Instalação

Da raiz do projeto:

```bat
INSTALAR.bat
ABRIR_CURADOR.bat
```

A primeira ação cria/repara `.venv`, a segunda abre `app.py`. Evite executar um launcher copiado para outra pasta: mantenha o projeto inteiro no mesmo diretório.

Em `config.yaml`, confira especialmente:

```yaml
paths:
  analysis_root: ../LDPORTO_VIDEO_ANALYZER/analysis
  output_root: ./output
  source_cache: ./source_cache
safety:
  require_first_test_approval_before_batch: true
```

Os caminhos são exemplos relativos à raiz do projeto. Ajuste `analysis_root` ao seu ambiente. As pastas de saída/cache podem conter revisões, mídias e aprovações: **não apague para fazer limpeza**.

## Atalhos Windows

| Atalho | Local | Ação |
| --- | --- | --- |
| `INSTALAR.bat` | raiz | Cria ambiente e instala dependências |
| `ABRIR_CURADOR.bat` | raiz | Abre GUI pelo `app.py` |
| `DIAGNOSTICO.bat` | `scripts/windows/` | Exibe Python, ferramentas e encoder NVENC |
| `TESTAR_1_CORTE.bat` | `scripts/windows/` | Executa `cli.py URL --test-one RANK` |

Com a pasta atual na raiz, execute:

```bat
scripts\windows\DIAGNOSTICO.bat
scripts\windows\TESTAR_1_CORTE.bat "https://www.youtube.com/watch?v=ID_DO_VIDEO" 1
```

O diagnóstico é informativo. O teste de corte necessita de análise/mídia e pode gerar arquivos em `output/`. Se falhar, consulte a mensagem, sem apagar dados de sessão.

## Etapas com aprovação

`CURAR` → `TESTAR 1 CORTE` → revisão humana do vídeo → `APROVAR TESTE` → `RENDERIZAR TODOS`.

A CLI contém outros comandos, como `--plan-series`, `--dossier-only`, `--preview-episode`, `--approve-episode` e `--render-approved-series`. Execute `python cli.py --help` para ver as opções da versão instalada e use os contratos de aprovação aplicáveis.

## Git e validação

O GitHub agora contém `main`, `release` e `develop`. Esta organização foi feita apenas em `develop`. Se sua cópia do Windows apresenta arquivos modificados, apagados ou não rastreados, faça backup e resolva o estado local **antes** de trocar de branch, restaurar ou limpar arquivos.

```bat
git fetch origin --prune
git status
git branch -avv
```

Em um ambiente Python com `pytest` disponível, `python -m pytest -q tests` é o comando de regressão. Testes anteriores documentados em relatórios não substituem a execução na máquina atual.
