# L.D.PORTO — Video Curator Studio 1.0

**Programa novo e independente**, desenvolvido para consumir o pacote editorial de execução R57 do Charlie Brown Jr. — Planeta Atlântida 2012. Não altera o `LDPORTO_VIDEO_CURATOR` antigo, nem requer GitHub, Qwen ou Ollama.

## Iniciar no Windows

1. Instale **Python 3.11+** (com Tkinter) e **FFmpeg + FFprobe** no PATH do Windows.
2. Execute `INSTALAR_WINDOWS.bat` (instala Pillow e yt-dlp).
3. Execute `INICIAR_WINDOWS.bat`.
4. O exemplo `example/CURADORIA_R57.zip` será carregado e verificado. Se preferir, use **CARREGAR CURADORIA ZIP**.
5. **BAIXAR VÍDEO DO YOUTUBE**: cole a URL HTTPS do vídeo e clique para baixar via yt-dlp; o exemplo R57 já preenche a URL do show. Você também pode usar **VINCULAR MP4 ORIGINAL** para um arquivo local. Baixe somente conteúdo que você tem direito de utilizar.
6. **SE O SHA256 DIVERGIR:** o download fica em `downloads/attempts/`. Clique **USAR DOWNLOAD NAS PRÉVIAS (REVISÃO)**: com o mesmo ID, áudio/vídeo, duração compatível (±3 s) e confirmação explícita, permite prévias com o hash real da cópia baixada. **Isso não prova que o áudio e os timestamps coincidam.** Confira cada prévia; se o trecho estiver deslocado, refaça a análise para o MP4 baixado. O pacote R57 e o SHA original permanecem intactos.
7. Escolha um Reel ou Story, revise início/fim, título, crop e legendas. O padrão usa **fonte horizontal preservada em canvas vertical com fundo desfocado**. Legendas ASR estão desligadas até conferência humana.
8. Gere a prévia em **540×960**, abra e assista, confirme revisão de áudio e câmera e clique **APROVAR PRÉVIA**.
9. Gere o MP4 final em **1080×1920**. Use **EXPORTAR CAPAS + PLANOS** para extrair as 72 capas, arquivos ASS/SRT e metadados.

**Importante:** o ZIP R57 contém 12 Reels, 60 Stories, 72 capas e rascunhos de legendas. Não contém o vídeo original; nada é publicado automaticamente. Os 60 Stories preservam os intervalos cronológicos contínuos, mas cortes de minuto podem cair no meio de fala/música — revise cada um antes de aprovar. Direitos de imagem/áudio permanecem por verificar.

## Recursos

- Verificação integral de SHA256 de todos os membros do ZIP e da mídia original.
- Download **manual** por campo URL, com yt-dlp, progresso, cancelamento, pasta isolada e relatório.
- **Modo de prévia com fonte alternativa:** confirma identidade e duração, nunca troca o SHA da análise e exige revisão de áudio/contexto por corte; ao mudar mídia, invalida aprovações.
- Entrada imutável, projetos salvos em `Vídeos/LDPORTO_CURATOR_STUDIO_PROJECTS`, com histórico de tentativas.
- Prévia e final usando FFmpeg/H.264 AAC; todas as saídas passam por FFprobe.
- Formato 9:16 com 16:9 integral preservado e fundo desfocado, ou crop central manual.
- Tarja de título branca profissional criada com Pillow, durante até 3,2 segundos.
- Legenda em ASS estilo amarelo/branco só quando explicitamente revisada.
- Capas originais do R57 exportáveis e geração opcional de nova capa baseada no MP4 verificado.
- Aprovação por *hash da prévia + plano de edição + fonte + versão do renderer*; editar vídeo invalida autorização anterior.
- Reels com normalização de áudio e fades muito curtos; Stories sem fade para preservar a continuidade.
- Finais somente após a aprovação da prévia. Relatório de origem e `EXPORT_MANIFEST.json`; nunca presume autorização de publicação.

O estado `FINAL_READY_REVIEW_RIGHTS` significa que o MP4 final está gerado, **não** que o conteúdo esteja liberado para postar.

## Arquitetura

- `ldporto_studio/core.py` — contrato R57, segurança, integridade, edições, revisão, histórico e aprovações.
- `ldporto_studio/rendering.py` — FFmpeg/FFprobe, composição, títulos, legendas e capas.
- `ldporto_studio/gui.py` — interface desktop Tkinter.
- `ldporto_studio/__main__.py` — automação CLI opcional.
- `example/CURADORIA_R57.zip` — pacote editorial original, sem alterações.
- `tests/` — testes com vídeo sintético + validação real do pacote R57.
- `docs/INSTALACAO_WINDOWS.md` — requisitos, limitações e solução de problemas.

## Comandos CLI

```bat
py -3 -m ldporto_studio import --zip "example\CURADORIA_R57.zip" --workdir "C:\curator_projects\CBJR"
py -3 -m ldporto_studio download --workdir "C:\curator_projects\CBJR" --url "https://www.youtube.com/watch?v=aUgESZsOGmY"
py -3 -m ldporto_studio review-download --workdir "C:\curator_projects\CBJR" --confirm-preview-review
py -3 -m ldporto_studio associate --workdir "C:\curator_projects\CBJR" --media "D:\Videos\CBJR_ORIGINAL.mp4"
py -3 -m ldporto_studio list --workdir "C:\curator_projects\CBJR" --kind reels
py -3 -m ldporto_studio preview --workdir "C:\curator_projects\CBJR" --id REEL_01
py -3 -m ldporto_studio approve --workdir "C:\curator_projects\CBJR" --id REEL_01 --watched --audio-ok --camera-ok
py -3 -m ldporto_studio final --workdir "C:\curator_projects\CBJR" --id REEL_01
py -3 -m ldporto_studio assets --workdir "C:\curator_projects\CBJR"
```

A aprovação CLI só deve ser executada depois que **uma pessoa** realmente assistiu e revisou a prévia. `--watched` não substitui essa verificação.

Teste com `py -3 -m unittest discover -s tests -v`.

### Revisar ou substituir legendas

A opção **VER SRT PARA REVISÃO** abre o rascunho de texto. Corrija e sincronize a legenda no editor da sua preferência, exporte em `.ass` UTF-8, e use **IMPORTAR ASS CORRIGIDA**. A nova legenda fica versionada fora do ZIP original e desativa a aprovação anterior; após conferir o áudio, marque **Conferi transcrição e áudio** e **Incluir karaokê ASS**, salve e gere nova prévia.
